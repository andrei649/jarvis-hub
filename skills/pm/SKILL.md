# PM

> Hephaestus' local project tracker (Cosmina build, BMW E93) — SQLite, no network

**Version:** 0.1.0
**Author:** claude
**Agents:** hephaestus

## Usage
Tracks tasks per project in a local SQLite DB (`memory_logs/pm.db`). Schema is
created automatically. Pure-local, no external calls.

## Commands
- `add_task <input>` — create a task: `<project>|<title>` (status defaults to todo)
- `list_tasks <input>` — list tasks for `<project>`
- `set_status <input>` — update status: `<id>|<status>` (todo/doing/blocked/done/backlog)

## Example Output
```
Task #1 adăugat în cosmina: „Toarnă fundația”.
Tasks cosmina (1):
- #1 [todo] Toarnă fundația
```
