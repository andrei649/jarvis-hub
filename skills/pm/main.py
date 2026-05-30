"""
pm/main.py — Hephaestus' project tracker skill (H2.7).

Loader-pattern skill backed by a local SQLite DB (memory_logs/pm.db). Tracks
tasks for projects like the Cosmina build and the BMW E93. Pure-local.

Commands (see get_commands):
  add_task <project>|<title>       — create a task (status defaults to 'todo')
  list_tasks <project>             — list tasks for a project
  set_status <id>|<status>         — update a task's status
"""

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger("jarvis.skills.pm")

DB_PATH = Path("memory_logs") / "pm.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    title   TEXT NOT NULL,
    status  TEXT NOT NULL DEFAULT 'todo'
);
"""

_VALID_STATUS = {"todo", "doing", "blocked", "done", "backlog"}


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def get_commands() -> list[str]:
    return ["add_task", "list_tasks", "set_status"]


# ── Programmatic API (used by tests / other modules) ────────────────

def create_task(project: str, title: str, status: str = "todo") -> dict:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO tasks (project, title, status) VALUES (?, ?, ?)",
        (project.lower(), title, status),
    )
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return {"status": "success", "id": tid}


def get_tasks(project: str = "") -> list[dict]:
    conn = _conn()
    if project:
        rows = conn.execute(
            "SELECT id, title, status FROM tasks WHERE project=? ORDER BY id",
            (project.lower(),),
        ).fetchall()
    else:
        rows = conn.execute("SELECT id, title, status FROM tasks ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_status(task_id: int, status: str) -> bool:
    conn = _conn()
    cur = conn.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


# ── Skill commands (text in / text out) ─────────────────────────────

async def add_task(args: str, context: dict = None) -> str:
    """`add_task <project>|<title>`"""
    parts = [p.strip() for p in (args or "").split("|")]
    if len(parts) < 2 or not parts[0] or not parts[1]:
        return "Folosire: add_task <proiect>|<titlu>"
    res = create_task(parts[0], parts[1])
    return f"Task #{res['id']} adăugat în {parts[0]}: „{parts[1]}”."


async def list_tasks(args: str, context: dict = None) -> str:
    """`list_tasks <project>`"""
    project = (args or "").strip().split(" ")[0]
    tasks = get_tasks(project)
    if not tasks:
        return f"Niciun task pentru {project or 'niciun proiect'}."
    lines = [f"- #{t['id']} [{t['status']}] {t['title']}" for t in tasks]
    head = f"Tasks {project}" if project else "Toate tasks"
    return f"{head} ({len(tasks)}):\n" + "\n".join(lines)


async def set_status(args: str, context: dict = None) -> str:
    """`set_status <id>|<status>`"""
    parts = [p.strip() for p in (args or "").split("|")]
    if len(parts) < 2:
        return "Folosire: set_status <id>|<status>"
    try:
        tid = int(parts[0])
    except ValueError:
        return f"Id invalid: '{parts[0]}'"
    status = parts[1].lower()
    if status not in _VALID_STATUS:
        return f"Status invalid. Permise: {', '.join(sorted(_VALID_STATUS))}"
    if update_status(tid, status):
        return f"Task #{tid} → {status}."
    return f"Nu există task #{tid}."


async def handle(cmd: str, args: str, context: dict = None) -> str:
    dispatch = {"add_task": add_task, "list_tasks": list_tasks, "set_status": set_status}
    fn = dispatch.get(cmd)
    if fn:
        return await fn(args, context)
    return f"[pm] comandă necunoscută: {cmd}"
