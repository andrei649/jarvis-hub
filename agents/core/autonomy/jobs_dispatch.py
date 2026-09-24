"""Durable manual requests; acceptance grants no execution authority."""

from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime

ACTIVE = ("queued", "running", "waiting")
ORIGINS = ("manual", "first_run", "first_run_asked")


def identity(job):
    return hashlib.sha256(
        json.dumps([job.action, job.options], sort_keys=True).encode()
    ).hexdigest()


class ManualDispatch:
    def __init__(self, store):
        self.store = store
        with store._lock:
            store._conn.execute("""CREATE TABLE IF NOT EXISTS job_requests (
                id TEXT PRIMARY KEY, job_id TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, fingerprint TEXT NOT NULL, run_id INTEGER,
                result TEXT, reason TEXT NOT NULL DEFAULT '')""")
            store._conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS job_request_active ON job_requests(job_id) WHERE status IN ('queued','running','waiting')"
            )
            # H687 — who asked: 'manual' (the owner's ▶ now, which runs even a paused
            # job), 'first_run' (queued at creation by the first-run policy, which the
            # drain checks again) or 'first_run_asked' (the create call asked for it).
            # Both first runs obey pause like a cron slot. Rows written before the
            # column existed were all manual.
            columns = {row[1] for row in store._conn.execute("PRAGMA table_info(job_requests)")}
            if "origin" not in columns:
                store._conn.execute(
                    "ALTER TABLE job_requests ADD COLUMN origin TEXT NOT NULL DEFAULT 'manual'"
                )
            store._conn.commit()

    @contextmanager
    def gate(self, job_id):
        # Fixed stripes bound filesystem growth even as owners delete/recreate jobs.
        stripe = int(hashlib.sha256(job_id.encode()).hexdigest()[:8], 16) % 64
        path = self.store._path.with_name(self.store._path.name + f".gate-{stripe}")
        from agents.core.vault import VaultError, _file_lock

        with ExitStack() as stack:
            try:
                stack.enter_context(_file_lock(path, timeout=0))
            except VaultError as exc:
                if str(exc) != "timed out waiting for vault lock":
                    raise
                yield False
                return
            yield True

    def enqueue(self, job_id, *, origin="manual"):
        if origin not in ORIGINS:
            raise ValueError(f"unknown request origin {origin!r}")
        # Resolve an already-finished approval before coalescing another click.
        for row in self.outstanding():
            if row["job_id"] == job_id and row["status"] == "waiting":
                current = self.get(row["id"])
                if current and current["status"] != "waiting":
                    self.state(
                        row["id"], current["status"], reason=current["reason"], run=current["run"]
                    )
        s = self.store
        with s._lock, s._conn:
            s._conn.execute("BEGIN IMMEDIATE")
            row = s._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            existing = s._conn.execute(
                "SELECT id, status, origin FROM job_requests WHERE job_id=? AND status IN ('queued','running','waiting')",
                (job_id,),
            ).fetchone()
            if existing:
                request_id = existing["id"]
                if origin == "manual" and existing["origin"] != "manual" and existing["status"] == "queued":
                    # The owner's ▶ now folds into a queued first run and makes it theirs.
                    s._conn.execute("UPDATE job_requests SET origin='manual' WHERE id=?", (request_id,))
            else:
                count = s._conn.execute(
                    "SELECT COUNT(*) FROM job_requests WHERE status IN ('queued','running','waiting')"
                ).fetchone()[0]
                if count >= 256:
                    raise ValueError("manual request capacity reached; wait for queued work")
                request_id = uuid.uuid4().hex
                s._conn.execute(
                    "INSERT INTO job_requests(id,job_id,status,created_at,fingerprint,origin) VALUES(?,?,?,?,?,?)",
                    (
                        request_id,
                        job_id,
                        "queued",
                        datetime.now(UTC).isoformat(),
                        identity(s._row_to_job(row)),
                        origin,
                    ),
                )
        return self.get(request_id)

    def cancel_queued(self, job_id, *, origin, reason):
        """Cancel the job's not-yet-claimed request of ``origin`` (one, or a tuple of
        them); how many were cancelled."""
        origins = (origin,) if isinstance(origin, str) else tuple(origin)
        s = self.store
        cancelled = 0
        with s._lock, s._conn:  # one transaction, one fixed statement per origin
            for one in origins:
                cancelled += s._conn.execute(
                    "UPDATE job_requests SET status='cancelled', reason=? WHERE job_id=? AND status='queued' AND origin=?",
                    (reason, job_id, one),
                ).rowcount
        return cancelled

    def get(self, request_id):
        s = self.store
        with s._lock:
            row = s._conn.execute("SELECT * FROM job_requests WHERE id=?", (request_id,)).fetchone()
            if row is None:
                return None
            result = dict(row)
            result.pop("fingerprint")
            encoded = result.pop("result")
            result["run"] = json.loads(encoded) if encoded else None
            if result["status"] == "waiting":
                run = s._conn.execute(
                    "SELECT * FROM job_runs WHERE id=? AND job_id=?",
                    (result["run_id"], result["job_id"]),
                ).fetchone()
                if run is None:
                    result.update(status="unknown", reason="pending execution evidence unavailable")
                elif run["status"] != "pending":
                    result.update(status="completed", run=dict(run))
            return result

    def outstanding(self):
        with self.store._lock:
            return [
                dict(r)
                for r in self.store._conn.execute(
                    "SELECT * FROM job_requests WHERE status IN ('queued','running','waiting') ORDER BY created_at,id LIMIT 256"
                )
            ]

    def state(self, request_id, status, *, reason="", run=None):
        s = self.store
        with s._lock, s._conn:
            s._conn.execute(
                "UPDATE job_requests SET status=?,reason=?,run_id=?,result=? WHERE id=?",
                (
                    status,
                    reason,
                    run.get("id") if run else None,
                    json.dumps(run) if run else None,
                    request_id,
                ),
            )
            s._conn.execute(
                "DELETE FROM job_requests WHERE id IN (SELECT id FROM job_requests WHERE status NOT IN ('queued','running','waiting') ORDER BY created_at DESC,id DESC LIMIT -1 OFFSET 200)"
            )

    def claim(self, request_id):
        """The claimed request's origin, or False. Hold the shared execution gate throughout the firing."""
        s = self.store
        with s._lock, s._conn:
            s._conn.execute("BEGIN IMMEDIATE")
            row = s._conn.execute(
                "SELECT * FROM job_requests WHERE id=? AND status='queued'", (request_id,)
            ).fetchone()
            if row is None:
                return False
            job = s._conn.execute("SELECT * FROM jobs WHERE id=?", (row["job_id"],)).fetchone()
            if job is None or identity(s._row_to_job(job)) != row["fingerprint"]:
                s._conn.execute(
                    "UPDATE job_requests SET status='cancelled',reason='job deleted or configuration changed' WHERE id=?",
                    (request_id,),
                )
                return False
            s._conn.execute("UPDATE job_requests SET status='running' WHERE id=?", (request_id,))
            return row["origin"] or "manual"

    async def drain(self, runner):
        for row in self.outstanding():
            if row["status"] == "waiting":
                current = self.get(row["id"])
                if current is not None and current["status"] != "waiting":
                    self.state(
                        row["id"], current["status"], reason=current["reason"], run=current["run"]
                    )
                continue
            with self.gate(row["job_id"]) as acquired:
                if not acquired:
                    continue
                current = self.get(row["id"])
                if current is None:
                    continue
                if row["status"] == "running" and current["status"] == "running":
                    # No process owns the gate: execution was interrupted. Never replay.
                    self.state(
                        row["id"],
                        "unknown",
                        reason="execution interrupted after claim; not replayed",
                    )
                elif origin := self.claim(row["id"]):
                    # A policy first run is checked again when it comes to run (H687):
                    # the job may have changed, or quiet hours or its first slot come.
                    due = getattr(runner, "first_run_due", None)
                    if origin == "first_run" and due is not None:
                        still, why = due(row["job_id"])
                        if not still:
                            self.state(row["id"], "cancelled", reason=f"first run no longer due: {why}")
                            continue
                    try:
                        # A first run obeys pause like a cron slot; only the owner's own
                        # ▶ now runs a paused job (H687).
                        run = await runner._fire_once(
                            row["job_id"], force=origin == "manual", expected_identity=row["fingerprint"]
                        )
                    except BaseException as exc:
                        self.state(
                            row["id"],
                            "unknown",
                            reason="execution interrupted after claim; not replayed",
                        )
                        if not isinstance(exc, Exception):
                            raise
                        continue
                    if self.store.get(row["job_id"]) is None:
                        self.state(
                            row["id"],
                            "unknown",
                            reason="job deleted during execution; effects not replayed",
                            run=run.as_dict(),
                        )
                        continue
                    self.state(
                        row["id"],
                        "waiting" if run.status == "pending" else "completed",
                        run=run.as_dict(),
                    )
                elif (current := self.get(row["id"])) and current["status"] == "cancelled":
                    self.state(row["id"], "cancelled", reason=current["reason"])
