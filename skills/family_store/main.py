"""
family_store/main.py — Frigga's local family data store (H2.8).

100% local SQLite, zero external network. Tracks simple per-person logs
(e.g. Max's sleep) so Frigga can answer "how did Max sleep?" with a trend.

Skill contract (see agents/core/skills/loader.py):
  - get_commands() lists command names
  - each command is a module-level async fn taking (args, context=None)
"""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("jarvis.skills.family_store")

# Lives under memory_logs/ which is git-ignored (and *.db too).
DB_PATH = Path("memory_logs") / "family.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sleep_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    person  TEXT NOT NULL,
    hours   REAL NOT NULL,
    ts      TEXT NOT NULL
);
"""


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def get_commands() -> list[str]:
    return ["log_sleep", "get_sleep"]


async def log_sleep(args: str, context: dict = None) -> str:
    """`log_sleep <person> <hours>` — record a sleep entry."""
    parts = (args or "").split()
    if len(parts) < 2:
        return "Folosire: log_sleep <persoană> <ore>"
    person = parts[0].lower()
    try:
        hours = float(parts[1].replace(",", "."))
    except ValueError:
        return f"Nu am înțeles orele: '{parts[1]}'"
    conn = _conn()
    conn.execute(
        "INSERT INTO sleep_log (person, hours, ts) VALUES (?, ?, ?)",
        (person, hours, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()
    return f"Am notat: {person.capitalize()} a dormit {hours:g}h."


async def get_sleep(args: str, context: dict = None) -> str:
    """`get_sleep <person>` — recent sleep + 7-entry average."""
    person = (args or "").strip().split(" ")[0].lower()
    if not person:
        return "Folosire: get_sleep <persoană>"
    conn = _conn()
    rows = conn.execute(
        "SELECT hours, ts FROM sleep_log WHERE person=? ORDER BY id DESC LIMIT 7",
        (person,),
    ).fetchall()
    conn.close()
    if not rows:
        return f"Nu am date de somn pentru {person.capitalize()}."
    last = rows[0]["hours"]
    avg = sum(r["hours"] for r in rows) / len(rows)
    return (
        f"{person.capitalize()}: ultima noapte {last:g}h, "
        f"media ultimelor {len(rows)} = {avg:.1f}h."
    )


async def handle(cmd: str, args: str, context: dict = None) -> str:
    """Fallback dispatcher if the loader routes via module.handle()."""
    if cmd == "log_sleep":
        return await log_sleep(args, context)
    if cmd == "get_sleep":
        return await get_sleep(args, context)
    return f"[family_store] comandă necunoscută: {cmd}"
