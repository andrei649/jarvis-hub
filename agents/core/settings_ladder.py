"""H258 — the settings store's schema version and its migration ladder.

Seeding (a new declaration gets its default) and value corrections (``_CHANGED_DEFAULTS``,
the retired-model rewrite) already run on every boot. This module adds the rest of
Hermes's ``config_migrations``:

* **a version stamp** in ``settings_meta`` (``schema_version``) and a **support floor**:
  a store stamped below :data:`SUPPORT_FLOOR` is not auto-migrated (its steps are refused
  and named, nothing is guessed), and a store stamped above :data:`STORE_VERSION` (a newer
  build ran on it) is left as it is — never stamped down;
* **ordered steps** that carry the owner's value across instead of orphaning it:
  ``rename`` (move a value to a new category/key), ``reshape`` (change a setting's kind,
  converting its value), ``retire`` (remove a setting). A value a step cannot carry — the
  new key already holds an owner value, the conversion fails or is refused by the new
  declaration — is kept in ``settings_retired`` (as stored: an encrypted secret stays
  encrypted) and named in the report, never dropped;
* **a post-migration report** (``settings_meta.last_report``): the steps that ran, the
  settings this build seeded into an existing store, and the environment variables this
  build declares that the previous one did not (``env_registry.introduced_since``), shown by
  ``nerva config check`` and ``nerva config migrate``.

An unstamped store is version 0: every build before H258. The ladder holds no step yet —
nothing in the repo has been renamed, re-shaped or retired since the stamp was introduced;
a future build adds its step here with its target version and bumps :data:`STORE_VERSION`.
The report never carries a value: setting and variable names only.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

#: This build's settings-store schema version.
STORE_VERSION = 1
#: The oldest stamped version this build still migrates (0: an unstamped store).
SUPPORT_FLOOR = 0

KINDS = ("rename", "reshape", "retire")

META_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings_retired (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    category   TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    kind       TEXT NOT NULL,
    step       TEXT NOT NULL,
    why        TEXT NOT NULL,
    retired_at REAL NOT NULL
);
"""

_ENC_PREFIX = "enc::v1::"


@dataclass(frozen=True)
class Step:
    """One rung. *version*: the store version it brings a store to; *setting*: the
    ``(category, key)`` it reads; *to*: the ``(category, key)`` a rename writes;
    *transform*: old value → new value (rename and reshape; None copies it as stored);
    *why*: the sentence the report shows."""

    version: int
    kind: str
    setting: tuple[str, str]
    why: str
    to: tuple[str, str] | None = None
    transform: Callable[[Any], Any] | None = None
    #: rename / reshape: the value the old declaration shipped. A store still holding it
    #: never chose it, so the new declaration's own default stands (nothing is carried).
    old_default: Any = None
    has_old_default: bool = False

    @property
    def name(self) -> str:
        return f"v{self.version}:{self.kind}:{'.'.join(self.setting)}"


#: The ladder, in order. Empty at version 1 (see the module docstring).
STEPS: tuple[Step, ...] = ()


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the meta tables inside the caller's transaction (``executescript`` would
    commit it first, so each statement is executed on its own)."""
    for statement in META_SCHEMA.split(";"):
        if statement.strip():
            conn.execute(statement)


def _meta(conn: sqlite3.Connection, key: str) -> str | None:
    try:
        row = conn.execute("SELECT value FROM settings_meta WHERE key=?", (key,)).fetchone()
    except sqlite3.OperationalError:            # an older store: no meta table yet
        return None
    return None if row is None else str(row[0])


def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO settings_meta (key, value) VALUES (?, ?)", (key, value))


def stamped_version(conn: sqlite3.Connection) -> int:
    """The store's stamped version; 0 for a store no build since H258 has stamped."""
    raw = _meta(conn, "schema_version")
    try:
        return int(raw) if raw is not None else 0
    except ValueError:
        return 0


def verdict(version: int, *, current: int | None = None, floor: int | None = None) -> str | None:
    """Why a store at *version* is not migrated (``too_old`` / ``newer``), or None."""
    current = STORE_VERSION if current is None else current
    floor = SUPPORT_FLOOR if floor is None else floor
    if version < floor:
        return "too_old"
    if version > current:
        return "newer"
    return None


def pending(version: int, steps: Iterable[Step] | None = None, *, current: int | None = None) -> list[Step]:
    """The steps a store at *version* still needs, in order."""
    current = STORE_VERSION if current is None else current
    return [s for s in (STEPS if steps is None else steps) if version < s.version <= current]


def refusal_text(version: int, why: str, *, current: int | None = None, floor: int | None = None) -> str:
    current = STORE_VERSION if current is None else current
    floor = SUPPORT_FLOOR if floor is None else floor
    if why == "too_old":
        return (f"the settings store is at schema version {version}, older than {floor}, the oldest this build "
                "migrates: it was not migrated (its values are untouched). Run a build that still migrates "
                "it first, or export the settings and import them here")
    return (f"the settings store is at schema version {version}, newer than this build's {current}: a newer "
            "build ran on it, so no migration step runs and the stamp is kept")


def _retire(conn: sqlite3.Connection, category: str, key: str, raw: str, kind: str, step: Step, why: str) -> None:
    conn.execute("INSERT INTO settings_retired (category, key, value, kind, step, why, retired_at) "
                 "VALUES (?,?,?,?,?,?,?)", (category, key, raw, kind, step.name, why, time.time()))


def _apply(conn: sqlite3.Connection, step: Step, spec: Mapping[tuple[str, str], Mapping[str, Any]],
           validate: Callable[[str, dict], list[str]]) -> dict[str, Any] | None:
    """Apply one step; the report line (names only), or None when the store has nothing
    the step reads."""
    category, key = step.setting
    row = conn.execute("SELECT value, kind FROM settings WHERE category=? AND key=?", (category, key)).fetchone()
    if row is None:
        return None
    raw, stored_kind = str(row[0]), str(row[1])
    line: dict[str, Any] = {"step": step.name, "kind": step.kind, "setting": f"{category}.{key}", "why": step.why}
    encrypted = raw.startswith(json.dumps(_ENC_PREFIX)[:-1])
    if step.kind == "retire":
        _retire(conn, category, key, raw, stored_kind, step, step.why)
        conn.execute("DELETE FROM settings WHERE category=? AND key=?", (category, key))
        line["kept_in"] = "settings_retired"
        return line
    target = step.to if step.kind == "rename" else step.setting
    if target is None or target not in spec:
        raise ValueError(f"{step.name}: its target is not a declared setting")
    declared = spec[target]
    line["to"] = ".".join(target)
    if step.kind == "reshape" and stored_kind == declared.get("kind"):
        return None                                     # already in the new shape
    try:
        old = json.loads(raw)
    except ValueError:
        old = None
    if step.has_old_default and not encrypted and old == step.old_default:
        if step.kind == "rename":
            conn.execute("DELETE FROM settings WHERE category=? AND key=?", (category, key))
        else:
            conn.execute("UPDATE settings SET value=?, kind=?, opts=? WHERE category=? AND key=?",
                         (json.dumps(declared.get("value")), declared.get("kind", "text"),
                          json.dumps(declared.get("opts", [])), category, key))
        line["carried"] = False
        line["problem"] = "it held the old shipped default: the new default applies"
        return line
    if step.transform is not None and encrypted:
        new, problems = None, ["a secret is never converted"]
    elif step.transform is not None:
        try:
            new = step.transform(old)
            problems = validate(target[0], {target[1]: new})
        except Exception as exc:  # noqa: BLE001 — a conversion that fails keeps the old value
            new, problems = None, [type(exc).__name__]
    else:
        new = old
        problems = [] if encrypted else validate(target[0], {target[1]: new})
    if step.kind == "rename":
        dst = conn.execute("SELECT value FROM settings WHERE category=? AND key=?", target).fetchone()
        if dst is not None and not _is_default(str(dst[0]), declared):
            problems = problems or ["the new setting already holds the owner's value"]
    if problems:
        _retire(conn, category, key, raw, stored_kind, step, "; ".join(problems))
        line["carried"] = False
        line["kept_in"] = "settings_retired"
        line["problem"] = "; ".join(str(p)[:120] for p in problems)
        if step.kind == "rename":
            conn.execute("DELETE FROM settings WHERE category=? AND key=?", (category, key))
        else:   # reshape: the row takes the new shape with its declared default
            conn.execute("UPDATE settings SET value=?, kind=?, opts=? WHERE category=? AND key=?",
                         (json.dumps(declared.get("value")), declared.get("kind", "text"),
                          json.dumps(declared.get("opts", [])), category, key))
        return line
    stored = raw if (encrypted and step.transform is None) else json.dumps(new)
    if step.kind == "rename":
        conn.execute("INSERT OR REPLACE INTO settings (category, key, value, label, kind, opts) VALUES (?,?,?,?,?,?)",
                     (target[0], target[1], stored, declared.get("label", ""), declared.get("kind", "text"),
                      json.dumps(declared.get("opts", []))))
        conn.execute("DELETE FROM settings WHERE category=? AND key=?", (category, key))
    else:
        conn.execute("UPDATE settings SET value=?, kind=?, opts=? WHERE category=? AND key=?",
                     (stored, declared.get("kind", "text"), json.dumps(declared.get("opts", [])), category, key))
    line["carried"] = True
    return line


def _is_default(raw: str, declared: Mapping[str, Any]) -> bool:
    try:
        return json.loads(raw) == declared.get("value")
    except ValueError:
        return False


def run(conn: sqlite3.Connection, *, spec: Mapping[tuple[str, str], Mapping[str, Any]],
        validate: Callable[[str, dict], list[str]], seeded: Iterable[str] = (), fresh: bool = False,
        steps: Iterable[Step] | None = None, current: int | None = None, floor: int | None = None,
        env_names: Iterable[str] | None = None) -> dict[str, Any]:
    """Bring the store on *conn* up the ladder inside the caller's transaction and write the
    report; returns it. *seeded*: the ``category.key`` names this init seeded; *fresh*: the
    store was just created (nothing is "new" to it); *env_names*: the variables this build
    declares (the registry's, by default)."""
    current = STORE_VERSION if current is None else current
    ensure_schema(conn)
    version = stamped_version(conn)
    why = verdict(version, current=current, floor=floor)
    report: dict[str, Any] = {"at": time.time(), "from_version": version, "to_version": version,
                              "steps": [], "new_settings": [], "new_env": []}
    if why is not None:
        report["refused"] = why
        report["detail"] = refusal_text(version, why, current=current, floor=floor)
    else:
        for step in pending(version, steps, current=current):
            line = _apply(conn, step, spec, validate)
            if line is not None:
                report["steps"].append(line)
        if version != current:
            _set_meta(conn, "schema_version", str(current))
        report["to_version"] = current
    if env_names is None:
        from agents.core import env_registry

        env_names = list(env_registry.entries())
    env_names = list(env_names)
    previous = _meta(conn, "env_names")
    if not fresh:
        report["new_settings"] = sorted(seeded)
        if previous is not None:
            try:
                known = set(json.loads(previous))
            except ValueError:
                known = set()
            report["new_env"] = [name for name in env_names if known and name not in known]
    _set_meta(conn, "env_names", json.dumps(env_names))
    if not fresh and (report["steps"] or report["new_settings"] or report["new_env"] or "refused" in report):
        _set_meta(conn, "last_report", json.dumps(report))
        if "refused" in report:
            logger.warning("settings store not migrated: %s", report["detail"])
        else:
            logger.info("settings store upgraded (schema %s → %s): %d step(s), %d new setting(s), %d new "
                        "environment variable(s) — `nerva config check` names them", version,
                        report["to_version"], len(report["steps"]), len(report["new_settings"]),
                        len(report["new_env"]))
    return report


def read_report(conn: sqlite3.Connection) -> tuple[int, dict[str, Any] | None]:
    """``(stamped version, the last post-migration report or None)``."""
    raw = _meta(conn, "last_report")
    try:
        report = json.loads(raw) if raw else None
    except ValueError:
        report = None
    return stamped_version(conn), report if isinstance(report, dict) else None


def retired(conn: sqlite3.Connection, limit: int = 100) -> list[dict[str, Any]]:
    """The values a step could not carry (names, step and why — never the value)."""
    try:
        rows = conn.execute("SELECT category, key, step, why, retired_at FROM settings_retired "
                            "ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [{"setting": f"{r[0]}.{r[1]}", "step": r[2], "why": r[3], "at": r[4]} for r in rows]


__all__ = ["KINDS", "STEPS", "STORE_VERSION", "SUPPORT_FLOOR", "Step", "ensure_schema", "pending",
           "read_report", "refusal_text", "retired", "run", "stamped_version", "verdict"]
