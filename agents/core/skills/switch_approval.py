"""Durable, approval-bound writes to the H329 skill switches."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
from collections.abc import Mapping

from agents.core import settings_db
from agents.core.autonomy.policy import RiskTier
from agents.core.kernel import kernel_enabled
from agents.core.permission_ledger import KIND, PermissionRequestError

from . import signing, switches

logger = logging.getLogger("jarvis.skills.switch_approval")
_REQUEST_LOCK = threading.RLock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_switch_revision (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL);
INSERT OR IGNORE INTO skill_switch_revision(id, revision) VALUES (1, 0);
CREATE TABLE IF NOT EXISTS skill_switch_requests (
 task_id INTEGER PRIMARY KEY, binding TEXT NOT NULL UNIQUE, record TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('pending','applied'))
);
CREATE TABLE IF NOT EXISTS skill_switch_receipts (
 task_id INTEGER PRIMARY KEY, binding TEXT NOT NULL, revision INTEGER NOT NULL,
 approver TEXT NOT NULL, grant_id TEXT NOT NULL, applied_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS skill_switch_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, task_id INTEGER,
 approver TEXT NOT NULL, binding TEXT, targets TEXT NOT NULL, channel TEXT NOT NULL,
 revision INTEGER NOT NULL, at REAL NOT NULL
);
CREATE TRIGGER IF NOT EXISTS skill_switch_insert AFTER INSERT ON settings
WHEN NEW.category='skills' AND NEW.key IN ('disabled','channel_disabled')
BEGIN UPDATE skill_switch_revision SET revision=revision+1 WHERE id=1; END;
CREATE TRIGGER IF NOT EXISTS skill_switch_update AFTER UPDATE OF value ON settings
WHEN NEW.category='skills' AND NEW.key IN ('disabled','channel_disabled')
BEGIN UPDATE skill_switch_revision SET revision=revision+1 WHERE id=1; END;
CREATE TRIGGER IF NOT EXISTS skill_switch_delete AFTER DELETE ON settings
WHEN OLD.category='skills' AND OLD.key IN ('disabled','channel_disabled')
BEGIN UPDATE skill_switch_revision SET revision=revision+1 WHERE id=1; END;
"""


def _connection():
    switches.preflight_persisted_rows()
    settings_db.ensure_initialized()
    conn = settings_db.get_conn()
    try:
        conn.executescript(_SCHEMA)
        return conn
    except BaseException:
        conn.close()
        raise


def _revision(conn) -> int:
    row = conn.execute("SELECT revision FROM skill_switch_revision WHERE id=1").fetchone()
    if row is None or not isinstance(row[0], int):
        raise settings_db.SettingsUnreadable("skill switch revision unavailable")
    return row[0]


def revision() -> int:
    conn = _connection()
    try:
        return _revision(conn)
    finally:
        conn.close()


def _write_state(conn, state: dict) -> None:
    for key in (switches.GLOBAL_KEY, switches.CHANNEL_KEY):
        result = conn.execute(
            "UPDATE settings SET value=? WHERE category=? AND key=?",
            (json.dumps(state[key], sort_keys=True), switches.CATEGORY, key),
        )
        if result.rowcount != 1:
            raise settings_db.SettingsUnreadable("skill switch row missing")


def _event(conn, action: str, *, task_id=None, approver: str, binding=None,
           targets: list[str], channel: str) -> None:
    conn.execute(
        "INSERT INTO skill_switch_events(action,task_id,approver,binding,targets,channel,revision,at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (action, task_id, approver, binding, json.dumps(targets), channel, _revision(conn), time.time()),
    )


def disable(skills: list, *, channel: str = "", actor: str = "owner") -> dict:
    """Narrow immediately. Even a redundant disable invalidates older requests."""
    if channel and switches.clean_channel(channel) != channel:
        raise ValueError("invalid skill channel")
    with switches._WRITE_LOCK:
        conn = _connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            settings_db._require_readable_store()
            before = switches.state_from_connection(conn)
            outcome = switches.plan(skills, enabled=False, channel=channel, now=before)
            # Updating one row, including on a no-op, moves the durable revision.
            _write_state(conn, outcome["state"])
            _event(conn, "disable", approver=actor, targets=[s.name for s in skills], channel=channel)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
    settings_db._changed(switches.CATEGORY, outcome["state"])
    return outcome


def _target_record(skills: list) -> list[dict]:
    records = []
    for skill in sorted(skills, key=lambda item: item.name.casefold()):
        loaded = getattr(skill, "source_fingerprint", None)
        live = signing.source_snapshot(skill.path).fingerprint
        if not loaded or loaded != live:
            raise ValueError(f"skill source changed or is unavailable: {skill.name}")
        records.append({"name": skill.name, "path": str(skill.path.resolve()), "fingerprint": live})
    return records


def _binding(record: dict) -> str:
    data = json.dumps(record, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _approval_label(record: dict) -> str:
    display = ", ".join(item["name"] for item in record["targets"])
    if len(display) > 120:
        display = display[:117] + "..."
    label = f"Switch on {display}{' on ' + record['channel'] if record['channel'] else ' everywhere'}"
    if record["category"]:
        label += f" (category {record['category'][:40]})"
    return label


def _expected_payload(record: dict, binding: str) -> dict:
    return {"kind": KIND, "surface": "skill_switch", "key": binding, "scope": "once",
            "requested_by": record["requested_by"], "reason": _approval_label(record),
            "risk_tier": int(RiskTier.EXTERNAL), "reversible": True}


def request_enable(orch, skills: list, *, channel: str = "", category: str = "",
                   requested_by: str = "owner") -> dict:
    """Queue one governed, exact-target approval; do not widen the switches."""
    with _REQUEST_LOCK:
        return _request_enable_locked(orch, skills, channel=channel, category=category,
                                      requested_by=requested_by)


def _request_enable_locked(orch, skills: list, *, channel: str, category: str,
                           requested_by: str) -> dict:
    ledger = getattr(orch, "permission_ledger", None)
    worker = getattr(orch, "autonomy", None)
    if channel and switches.clean_channel(channel) != channel:
        raise ValueError("invalid skill channel")
    conn = _connection()
    try:
        # SQLite's read transaction pins the switch rows and revision to one snapshot.
        conn.execute("BEGIN")
        state = switches.state_from_connection(conn)
        outcome = switches.plan(skills, enabled=True, channel=channel, now=state)
        if not outcome["changed"]:
            conn.rollback()
            return {**outcome, "status": "unchanged"}
        if (not kernel_enabled() or ledger is None or getattr(ledger, "_authorizer", None) is None
                or worker is None or not callable(getattr(worker, "govern_enqueue", None))):
            raise PermissionRequestError("skill switch approval intake or Action Kernel unavailable")
        record = {"targets": _target_record(skills), "channel": channel,
                  "category": category, "revision": _revision(conn), "requested_by": requested_by}
        conn.rollback()
        binding = _binding(record)
        prior = conn.execute("SELECT task_id FROM skill_switch_requests WHERE binding=? AND status='pending'",
                             (binding,)).fetchone()
        task_queue = getattr(worker, "queue", None)
        if prior is not None and callable(getattr(task_queue, "get", None)):
            existing_task = task_queue.get(prior["task_id"])
            if existing_task is None or getattr(existing_task, "status", None) in {
                    "done", "failed", "rejected", "quarantined", "expired"}:
                conn.execute("DELETE FROM skill_switch_requests WHERE task_id=? AND status='pending'",
                             (prior["task_id"],))
                conn.commit()
                prior = None
            elif (getattr(existing_task, "kind", None) != KIND
                  or not isinstance(getattr(existing_task, "payload", None), Mapping)
                  or dict(existing_task.payload) != _expected_payload(record, binding)
                  or getattr(existing_task, "title", None) != _approval_label(record)
                  or getattr(existing_task, "agent", None) != "jarvis"):
                raise PermissionRequestError("pending approval task binding mismatch")
        if prior is not None:
            return {**outcome, "status": "pending", "task_id": prior["task_id"],
                    "changed": [], "pending": outcome["changed"], "state": state}
        label = _approval_label(record)
        task_id = ledger.request("skill_switch", binding, "once", requested_by,
                                 worker.govern_enqueue, title=label, reason=label)
        if not isinstance(task_id, int) or isinstance(task_id, bool) or task_id <= 0:
            raise PermissionRequestError("approval intake did not return a durable task")
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("INSERT INTO skill_switch_requests(task_id,binding,record,status) VALUES (?,?,?,'pending')",
                         (task_id, binding, json.dumps(record, sort_keys=True)))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            # Another process won. The newly queued task has no request row and
            # cannot pass apply_approved; surface the original pending task.
            prior = conn.execute("SELECT task_id FROM skill_switch_requests WHERE binding=? AND status='pending'",
                                 (binding,)).fetchone()
            if prior is None:
                raise
            task_id = prior["task_id"]
        return {**outcome, "status": "pending", "task_id": task_id,
                "changed": [], "pending": outcome["changed"], "state": state}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


async def apply_approved(task, *, ledger, loader, usage=None, intent_log=None) -> dict:
    """Apply one human-approved request with attribution in the same settings commit."""
    payload = getattr(task, "payload", None)
    task_id = getattr(task, "id", None)
    if (getattr(task, "kind", None) != KIND or not isinstance(payload, Mapping)
            or payload.get("surface") != "skill_switch" or payload.get("scope") != "once"
            or not isinstance(task_id, int) or isinstance(task_id, bool)):
        return {"status": "refused", "reason": "task_binding_mismatch"}
    if not kernel_enabled() or getattr(ledger, "_authorizer", None) is None:
        return {"status": "refused", "reason": "kernel_unavailable"}
    conn = _connection()
    try:
        row = conn.execute("SELECT * FROM skill_switch_requests WHERE task_id=?", (task_id,)).fetchone()
        if row is not None and row["status"] == "applied" and row["binding"] == payload.get("key"):
            receipt = conn.execute("SELECT grant_id FROM skill_switch_receipts WHERE task_id=? AND binding=?",
                                   (task_id, row["binding"])).fetchone()
            if receipt is not None:
                try:
                    ledger.consume_skill_switch_grant(receipt["grant_id"], task_id=task_id, binding=row["binding"])
                except Exception:
                    logger.warning("approved skill switch grant cleanup pending", exc_info=True)
            return {"status": "refused", "reason": "task_already_applied"}
        if row is None or row["status"] != "pending" or row["binding"] != payload.get("key"):
            return {"status": "refused", "reason": "task_binding_mismatch"}
        record = json.loads(row["record"])
        if (_binding(record) != row["binding"] or dict(payload) != _expected_payload(record, row["binding"])
                or getattr(task, "title", None) != _approval_label(record)
                or getattr(task, "agent", None) != "jarvis"):
            return {"status": "refused", "reason": "task_binding_mismatch"}
        grant_result = await ledger.apply_grant(task)
        if grant_result.get("status") != "ok" or grant_result.get("grant_status") != "active":
            return {"status": "refused", "reason": grant_result.get("reason", "grant_not_active")}
        grant = ledger.get(grant_result["grant_id"])
        if (grant is None or grant.task_id != task_id or grant.scope != "once"
                or grant.key != row["binding"] or grant.surface != "skill_switch"
                or not grant.granted_by):
            return {"status": "refused", "reason": "task_binding_mismatch"}
        with switches._WRITE_LOCK:
            conn.execute("BEGIN IMMEDIATE")
            settings_db._require_readable_store()
            fresh = conn.execute("SELECT * FROM skill_switch_requests WHERE task_id=?", (task_id,)).fetchone()
            if (fresh is None or fresh["status"] != "pending" or fresh["binding"] != row["binding"]
                    or fresh["record"] != row["record"] or _revision(conn) != record["revision"]):
                conn.rollback()
                return {"status": "refused", "reason": "stale_switch_request"}
            current = []
            for target in record["targets"]:
                skill = loader.skills.get(target["name"])
                if (skill is None or str(skill.path.resolve()) != target["path"]
                        or getattr(skill, "source_fingerprint", None) != target["fingerprint"]
                        or signing.source_snapshot(skill.path).fingerprint != target["fingerprint"]):
                    conn.rollback()
                    return {"status": "refused", "reason": "stale_skill_source"}
                current.append(skill)
            if record["category"]:
                from agents.core.routers.skills import _skill_category

                current_members = {s.name for s in loader.skills.values()
                                   if _skill_category(s).casefold() == record["category"].casefold()}
                if current_members != {s.name for s in current}:
                    conn.rollback()
                    return {"status": "refused", "reason": "stale_skill_category"}
            state = switches.state_from_connection(conn)
            outcome = switches.plan(current, enabled=True, channel=record["channel"], now=state)
            _write_state(conn, outcome["state"])
            conn.execute("UPDATE skill_switch_requests SET status='applied' WHERE task_id=?", (task_id,))
            conn.execute("INSERT INTO skill_switch_receipts(task_id,binding,revision,approver,grant_id,applied_at) "
                         "VALUES (?,?,?,?,?,?)", (task_id, row["binding"], _revision(conn), grant.granted_by,
                                                grant.id, time.time()))
            _event(conn, "enable", task_id=task_id, approver=grant.granted_by,
                   binding=row["binding"], targets=outcome["changed"], channel=record["channel"])
            conn.commit()
        settings_db._changed(switches.CATEGORY, outcome["state"])
        try:
            ledger.consume_skill_switch_grant(grant.id, task_id=task_id, binding=row["binding"])
        except Exception:
            # The settings receipt is the sole effect authority and bars replay even
            # when ledger cleanup must be retried on a later worker invocation.
            logger.warning("approved skill switch grant cleanup pending", exc_info=True)
        if usage is not None and callable(getattr(usage, "bump", None)):
            for name in outcome["changed"]:
                try:
                    usage.bump(name, "switch_on")
                except Exception:
                    logger.warning("skill usage clock could not be updated", exc_info=True)
        if intent_log is not None and callable(getattr(intent_log, "record", None)):
            try:
                intent_log.record(actor=grant.granted_by, action="skill.enable",
                                  why="approved skill switch task applied", cause="skills.switch",
                                  metadata={"task_id": task_id, "skills": outcome["changed"]})
            except Exception:
                logger.warning("optional skill switch projection failed", exc_info=True)
        return {"status": "ok", "task_id": task_id, "changed": outcome["changed"]}
    except (sqlite3.Error, settings_db.SettingsUnreadable, ValueError, OSError):
        conn.rollback()
        logger.warning("skill switch approval could not be applied", exc_info=True)
        return {"status": "failed", "reason": "switch_store_unavailable"}
    finally:
        conn.close()
