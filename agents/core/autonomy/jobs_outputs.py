"""Bounded latest substantive output for same-profile scheduled-job chaining."""

from __future__ import annotations

import json
import re

MAX_OUTPUT_CHARS = 8_000
MAX_OUTPUT_BYTES = 32 * 1024
MAX_CONTEXT_BYTES = 64 * 1024
MAX_CONTEXT_SOURCES = 8
_ID = re.compile(r"[0-9a-f]{12}\Z")


def context_ids(value: object) -> list[str]:
    if isinstance(value, str):
        entries = [value]
    elif isinstance(value, list):
        entries = value
    else:
        raise ValueError("context_from must be an ID or list of IDs")
    if len(entries) > MAX_CONTEXT_SOURCES:
        raise ValueError("context_from has too many sources")
    result = []
    for item in entries:
        if not isinstance(item, str):
            raise ValueError("context_from IDs must be text")
        normalized = item.lower()
        if normalized != "self" and not _ID.fullmatch(normalized):
            raise ValueError("context_from requires 12-hex job IDs or self")
        if normalized in result:
            raise ValueError("context_from contains a duplicate source")
        result.append(normalized)
    return result


def bounded_content(value: str) -> tuple[str, bool]:
    if not isinstance(value, str):
        raise ValueError("job output must be text")
    clipped = value[:MAX_OUTPUT_CHARS]
    if len(clipped.encode("utf-8")) > MAX_OUTPUT_BYTES:
        lower, upper = 0, len(clipped)
        while lower < upper:
            middle = (lower + upper + 1) // 2
            if len(clipped[:middle].encode("utf-8")) <= MAX_OUTPUT_BYTES:
                lower = middle
            else:
                upper = middle - 1
        clipped = clipped[:lower]
    return clipped, clipped != value


def render_context_block(source_id: str, content: str, bounded: bool) -> str:
    """Render exactly the host text budgeted for one external job output."""
    from agents.core.security.quarantine import fence_tool_result

    fenced, _ = fence_tool_result(json.dumps({"output": content}, ensure_ascii=True),
                                 source="scheduled-job-context")
    return (f"\n\n## Output from job '{source_id}'\n"
            "Use this preceding job's output as context for your analysis.\n"
            + ("This saved output is bounded and incomplete.\n" if bounded else "")
            + fenced)


class JobOutputs:
    def __init__(self, store) -> None:
        self.store = store
        with store._lock:
            store._conn.execute("""CREATE TABLE IF NOT EXISTS job_latest_outputs (
                job_id TEXT PRIMARY KEY, run_id INTEGER NOT NULL,
                source_created_at TEXT NOT NULL, content TEXT NOT NULL,
                recorded_at TEXT NOT NULL, bounded INTEGER NOT NULL)""")
            store._conn.commit()

    def _publish_locked(self, conn, job_id: str, run_id: int, content: str,
                        recorded_at: str, expected_created_at: str) -> bool:
        clipped, bounded = bounded_content(content)
        if not clipped.strip():
            return False
        source = conn.execute("SELECT created_at FROM jobs WHERE id=? AND created_at=?",
                              (job_id, expected_created_at)).fetchone()
        if source is None:
            return False
        run = conn.execute("SELECT status FROM job_runs WHERE id=? AND job_id=?", (run_id, job_id)).fetchone()
        if run is None or run["status"] != "ok":
            return False
        conn.execute("""INSERT INTO job_latest_outputs VALUES (?,?,?,?,?,?)
            ON CONFLICT(job_id) DO UPDATE SET run_id=excluded.run_id,
            source_created_at=excluded.source_created_at,content=excluded.content,
            recorded_at=excluded.recorded_at,bounded=excluded.bounded""",
            (job_id, run_id, source["created_at"], clipped, recorded_at, int(bounded)))
        return True

    def get_locked(self, conn, job_id: str) -> dict | None:
        row = conn.execute("""SELECT o.* FROM job_latest_outputs o
                JOIN jobs j ON j.id=o.job_id AND j.created_at=o.source_created_at
                WHERE o.job_id=?""", (job_id,)).fetchone()
        return dict(row) if row else None

    def get(self, job_id: str) -> dict | None:
        with self.store._lock:
            return self.get_locked(self.store._conn, job_id)

    def snapshot_locked(self, conn, destination_id: str, options: dict) -> list[dict]:
        result = []
        total = 0
        for source_id in context_ids(options.get("context_from", [])):
            if source_id == "self" or source_id == destination_id:
                continue
            row = conn.execute("""SELECT o.* FROM job_latest_outputs o
                JOIN jobs j ON j.id=o.job_id AND j.created_at=o.source_created_at
                WHERE o.job_id=?""", (source_id,)).fetchone()
            if row is None or not row["content"]:
                continue
            content = row["content"]
            remaining = MAX_CONTEXT_BYTES - total
            if remaining <= 0:
                break
            def size(prefix: str, *, bounded: bool, current_id: str = source_id) -> int:
                return len(render_context_block(current_id, prefix, bounded).encode("utf-8"))

            if size(content, bounded=bool(row["bounded"])) > remaining:
                lower, upper = 0, len(content)
                while lower < upper:
                    middle = (lower + upper + 1) // 2
                    if size(content[:middle], bounded=True) <= remaining:
                        lower = middle
                    else:
                        upper = middle - 1
                content = content[:lower]
            if not content:
                break
            bounded = bool(row["bounded"]) or content != row["content"]
            result.append({"job_id": source_id, "source_created_at": row["source_created_at"],
                           "content": content, "bounded": bounded})
            total += size(content, bounded=bounded)
        return result

    def snapshot(self, destination_id: str, options: dict) -> list[dict]:
        with self.store._lock:
            return self.snapshot_locked(self.store._conn, destination_id, options)

    def still_live(self, source_id: str, created_at: str) -> bool:
        with self.store._lock:
            row = self.store._conn.execute("SELECT 1 FROM jobs WHERE id=? AND created_at=?",
                                           (source_id, created_at)).fetchone()
        return row is not None
