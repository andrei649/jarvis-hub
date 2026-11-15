"""Exact, bounded records for one owner-authored hub restart.

These values are queue evidence. None is a permit to stop a service by itself.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import Any

from .mediation import canonical_json

KIND = "hub.restart"
TITLE = "Restart Nerva"
PREVIEW = "Restart Nerva after current work finishes; notify the requesting owner when it is online."
SOURCE_PURPOSE_V1 = "h084-hub-restart-source-v1"
SOURCE_PURPOSE = "h084-hub-restart-source-v2"
ARM_PURPOSE = "h084-hub-restart-arm-v1"
COMPLETION_PURPOSE = "h084-hub-restart-completion-v1"
SOURCE_TTL_MS = 300_000
MAX_RESTART_ROWS = 20_000
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_BOOT = re.compile(r"[A-Za-z0-9_-]{16,128}\Z")


class RestartStateUnavailable(RuntimeError):
    """Restart receipt storage could not be read or authenticated."""


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def valid_digest(value: Any) -> bool:
    return type(value) is str and _HEX.fullmatch(value) is not None


def valid_boot(value: Any) -> bool:
    return type(value) is str and _BOOT.fullmatch(value) is not None


def valid_requester(value: Any) -> bool:
    if type(value) is not dict or set(value) != {
        "provider_key", "bot_id", "update_id", "message_id", "chat_id", "sender_id", "inbox_id"
    }:
        return False
    ids = [value[name] for name in ("bot_id", "update_id", "message_id", "chat_id", "sender_id")]
    if any(type(item) is not int or not 0 < item <= (1 << 63) - 1 for item in ids):
        return False
    if value["chat_id"] != value["sender_id"]:
        return False
    if value["provider_key"] != f"telegram:{value['bot_id']}:{value['update_id']}":
        return False
    inbox = value["inbox_id"]
    return type(inbox) is str and 1 <= len(inbox) <= 128 and inbox.isascii() and inbox.isprintable()


def request_payload(requester: dict) -> dict:
    return {"operation": "restart", "requester": dict(requester), "risk_tier": 3,
            "reversible": False, "preview": PREVIEW}


_request_payload = request_payload


def issue_source(queue, *, orch, principal, source, title=TITLE, request_payload: dict):
    """Sign only the current original Telegram owner command, not route fields."""
    from agents.core import hub_restart
    from agents.core.command_source import (
        InboundCommandSource,
        restart_command_text,
        source_for_dispatch,
    )

    try:
        if (queue.mediation_mode != "enforce" or title != TITLE
                or type(source) is not InboundCommandSource
                or getattr(orch, "autonomy_queue", None) is not queue
                or getattr(getattr(orch, "autonomy", None), "queue", None) is not queue
                or hub_restart.available() is not True
                or source_for_dispatch(text="/restart", principal=principal, orch=orch) is not source):
            return None
        candidate = source.candidate
        if not restart_command_text(candidate.text):
            return None
        requester = {"provider_key": source.provider_id, "bot_id": candidate.bot_id,
                     "update_id": candidate.update_id, "message_id": candidate.message_id,
                     "chat_id": candidate.chat_id, "sender_id": candidate.sender_id,
                     "inbox_id": source.inbox_id}
        if not valid_requester(requester) or request_payload != _request_payload(requester):
            return None
        now = queue._clock_ms()
        body = {"purpose": SOURCE_PURPOSE, "version": 2, "kind": KIND,
                "agent": "owner", "nonce": uuid.uuid4().hex,
                "queue_epoch": queue._restart_epoch, "issued_at_ms": now,
                "expires_at_ms": now + SOURCE_TTL_MS, "title": TITLE,
                "payload_sha256": digest(request_payload), "requester": requester,
                "generation": candidate.generation, "original_text": candidate.text}
        signature = queue._mediation_signer.sign(canonical_json(body))
        return RestartSourceTicket(body, signature) if signature else None
    except Exception:
        return None


def ticket_for_payload(queue, payload: dict, *, title: str, agent: str,
                       current: bool) -> RestartSourceTicket | None:
    from agents.core.command_source import restart_command_text

    try:
        if (type(payload) is not dict or set(payload) != {
                "operation", "requester", "risk_tier", "reversible", "preview", "source_ticket"
        } or agent != "owner" or title != TITLE):
            return None
        ticket = payload["source_ticket"]
        if type(ticket) is not dict or set(ticket) != {"body", "signature"}:
            return None
        body = ticket["body"]
        base_fields = {"purpose", "version", "kind", "agent", "nonce", "queue_epoch",
                       "issued_at_ms", "expires_at_ms", "title", "payload_sha256",
                       "requester", "generation"}
        if type(body) is not dict or type(body.get("version")) is not int:
            return None
        version = body["version"]
        # V1 was issued only for literal /restart and had no text field. It
        # remains verifiable for already-persisted tasks across a later boot.
        # V2 binds the exact original observed text, including its casing and
        # punctuation, without trusting a rewritten registry route string.
        if ((version == 1 and (set(body) != base_fields or body.get("purpose") != SOURCE_PURPOSE_V1))
                or (version == 2 and (set(body) != base_fields | {"original_text"}
                                      or body.get("purpose") != SOURCE_PURPOSE
                                      or not restart_command_text(body.get("original_text"))))
                or version not in {1, 2}):
            return None
        requester = body["requester"]
        if (body["kind"] != KIND
                or body["agent"] != "owner" or body["title"] != TITLE
                or not valid_requester(requester) or payload["requester"] != requester
                or {key: value for key, value in payload.items() if key != "source_ticket"}
                != request_payload(requester)
                or body["payload_sha256"] != digest(request_payload(requester))
                or type(body["nonce"]) is not str or not re.fullmatch(r"[0-9a-f]{32}", body["nonce"])
                or type(body["queue_epoch"]) is not str
                or not re.fullmatch(r"[0-9a-f]{32}", body["queue_epoch"])
                or type(body["generation"]) is not str
                or not 1 <= len(body["generation"]) <= 128
                or type(body["issued_at_ms"]) is not int
                or type(body["expires_at_ms"]) is not int
                or body["expires_at_ms"] - body["issued_at_ms"] != SOURCE_TTL_MS
                or not queue._mediation_signer.verify(canonical_json(body), ticket["signature"])):
            return None
        if current and (body["queue_epoch"] != queue._restart_epoch
                        or not body["issued_at_ms"] <= queue._clock_ms() <= body["expires_at_ms"]):
            return None
        return RestartSourceTicket(body, ticket["signature"])
    except Exception:
        return None


def source_insert_locked(queue, task_id: int, ticket: RestartSourceTicket) -> None:
    from .queue import HubRestartReplay, TaskQueueError

    count = queue._conn.execute("SELECT COUNT(*) FROM task_restart_sources").fetchone()[0]
    if count >= MAX_RESTART_ROWS:
        raise TaskQueueError("restart source capacity reached")
    requester = ticket.body["requester"]
    nonce_sha = hashlib.sha256(ticket.body["nonce"].encode()).hexdigest()
    provider_sha = hashlib.sha256(requester["provider_key"].encode()).hexdigest()
    try:
        queue._conn.execute(
            """INSERT INTO task_restart_sources
               (task_id,nonce_sha256,provider_sha256,ticket_sha256,queue_epoch)
               VALUES(?,?,?,?,?)""",
            (task_id, nonce_sha, provider_sha, digest(ticket.as_dict()),
             ticket.body["queue_epoch"]),
        )
    except Exception as exc:
        import sqlite3

        if isinstance(exc, sqlite3.IntegrityError):
            raise HubRestartReplay("restart source already recorded") from exc
        raise


def _source_current_locked(queue, task) -> tuple[RestartSourceTicket, dict] | None:
    ticket = ticket_for_payload(queue, task.payload, title=task.title,
                                agent=task.agent, current=False)
    if ticket is None:
        return None
    row = queue._conn.execute(
        "SELECT * FROM task_restart_sources WHERE task_id=?", (task.id,)
    ).fetchone()
    if (row is None or row["ticket_sha256"] != digest(ticket.as_dict())
            or row["queue_epoch"] != ticket.body["queue_epoch"]
            or row["nonce_sha256"] != hashlib.sha256(ticket.body["nonce"].encode()).hexdigest()
            or row["provider_sha256"] != hashlib.sha256(
                ticket.body["requester"]["provider_key"].encode()).hexdigest()):
        return None
    return ticket, ticket.body["requester"]


def _mediation_current_locked(queue, row, *, at_ms: int, current_policy: bool) -> bool:
    from .mediation import canonical_digest, verify_receipt

    try:
        if queue._validated_mediation_snapshot_locked() is None:
            return False
        receipt, expected, sha = queue._row_receipt_and_expectation(row)
        if (row["kind"] != KIND or row["agent"] != "owner" or int(row["risk_tier"]) != 3
                or row["mediation_task_sha256"] != sha
                or receipt.effective_tier != 3
                or not row["mediation_execution_id"]
                or current_policy and (queue.mediation_mode != "enforce"
                                       or expected.policy_revision != queue._mediation_policy_revision
                                       or not queue._scope_allowed(expected.scope))
                or not verify_receipt(queue._mediation_signer, receipt,
                                      expected=expected, now_ms=at_ms)):
            return False
        receipt_sha = canonical_digest(receipt.to_dict())
        for outcome, execution_id in (("authorized_enqueue", ""),
                                      ("governed", row["mediation_execution_id"])):
            count = queue._conn.execute(
                """SELECT COUNT(*) FROM task_mediation_events
                   WHERE task_id=? AND enqueue_id=? AND outcome=?
                     AND execution_id=? AND receipt_id=? AND receipt_sha256=?""",
                (row["id"], expected.enqueue_id, outcome, execution_id,
                 receipt.receipt_id, receipt_sha),
            ).fetchone()[0]
            if count != 1:
                return False
        return True
    except Exception:
        return False


def _human_restart(task) -> bool:
    from .irreversible import MACHINE_DECIDERS

    return (task.kind == KIND and task.agent == "owner" and task.title == TITLE
            and task.decision in {"accept", "approve"}
            and type(task.decided_by) is str
            and task.decided_by.strip().lower() not in MACHINE_DECIDERS
            and type(task.human_decision) is dict
            and task.human_decision.get("action") == task.decision
            and task.human_decision.get("by") == task.decided_by
            and type(task.human_decision.get("id")) is str
            and re.fullmatch(r"[0-9a-f]{32}", task.human_decision["id"]) is not None
            and task.risk_tier == 3 and task.attempts == 1)


def _running_locked(queue, row, task, *, at_ms: int) -> tuple[str, dict] | None:
    from .queue import _row_to_task

    if row is None or row["status"] != "running":
        return None
    persisted = _row_to_task(row)
    fingerprint = queue.execution_fingerprint(persisted)
    if (not _human_restart(persisted) or task.status != "running"
            or queue.execution_fingerprint(task) != fingerprint or not fingerprint
            or not _mediation_current_locked(queue, row, at_ms=at_ms, current_policy=True)):
        return None
    source = _source_current_locked(queue, persisted)
    return (fingerprint, source[1]) if source else None


def _verified_from_body(body: dict) -> VerifiedRestart:
    requester = body["requester"]
    return VerifiedRestart(body["task_id"], digest(body), body["boot_id"],
                           requester["provider_key"], requester["bot_id"],
                           requester["chat_id"], requester["sender_id"])


def arm(queue, task, boot_id: str) -> RestartArm | None:
    if not valid_boot(boot_id) or queue.mediation_mode != "enforce":
        return None
    fingerprint = queue.execution_fingerprint(task)
    if not fingerprint or queue.validate_mediated_execution(task, fingerprint) is not True:
        return None
    with queue._lock:
        try:
            queue._conn.execute("BEGIN IMMEDIATE")
            row = queue._conn.execute("SELECT * FROM tasks WHERE id=?", (task.id,)).fetchone()
            now = queue._clock_ms()
            current = _running_locked(queue, row, task, at_ms=now)
            if current is None or queue._conn.execute(
                    "SELECT 1 FROM task_restart_intents WHERE task_id=?", (task.id,)).fetchone():
                queue._conn.rollback()
                return None
            fingerprint, requester = current
            body = {"purpose": ARM_PURPOSE, "version": 1, "task_id": task.id,
                    "boot_id": boot_id, "execution_fingerprint": fingerprint,
                    "requester": requester, "armed_at_ms": now}
            encoded = canonical_json(body)
            signature = queue._mediation_signer.sign(encoded)
            if signature is None:
                queue._conn.rollback()
                return None
            intent_digest = hashlib.sha256(encoded).hexdigest()
            queue._conn.execute(
                """INSERT INTO task_restart_intents
                   (task_id,boot_id,arm_body,arm_signature,intent_digest)
                   VALUES(?,?,?,?,?)""",
                (task.id, boot_id, encoded, signature, intent_digest),
            )
            queue._conn.commit()
            queue._restart_boot_id = boot_id
            return RestartArm(task.id, intent_digest, boot_id, requester["provider_key"],
                              requester["bot_id"], requester["chat_id"], requester["sender_id"])
        except Exception:
            queue._conn.rollback()
            return None


def complete(queue, task, result: dict) -> VerifiedRestart | None:
    if (type(result) is not dict or set(result) != {"status", "phase", "intent_digest"}
            or result["status"] != "ok" or result["phase"] != "armed"
            or not valid_digest(result["intent_digest"])):
        return None
    with queue._lock:
        try:
            queue._conn.execute("BEGIN IMMEDIATE")
            row = queue._conn.execute("SELECT * FROM tasks WHERE id=?", (task.id,)).fetchone()
            now = queue._clock_ms()
            current = _running_locked(queue, row, task, at_ms=now)
            intent = queue._conn.execute(
                "SELECT * FROM task_restart_intents WHERE task_id=?", (task.id,)
            ).fetchone()
            if current is None or intent is None or intent["completion_body"] is not None:
                queue._conn.rollback()
                return None
            fingerprint, requester = current
            arm_body = json_load(intent["arm_body"])
            if (intent["intent_digest"] != result["intent_digest"]
                    or digest(arm_body) != intent["intent_digest"]
                    or not queue._mediation_signer.verify(intent["arm_body"], intent["arm_signature"])
                    or arm_body != {"purpose": ARM_PURPOSE, "version": 1, "task_id": task.id,
                                    "boot_id": intent["boot_id"],
                                    "execution_fingerprint": fingerprint,
                                    "requester": requester,
                                    "armed_at_ms": arm_body.get("armed_at_ms")}):
                queue._conn.rollback()
                return None
            completion = {"purpose": COMPLETION_PURPOSE, "version": 1,
                          "task_id": task.id, "intent_digest": intent["intent_digest"],
                          "execution_fingerprint": fingerprint,
                          "result_sha256": digest(result), "completed_at_ms": now}
            encoded = canonical_json(completion)
            signature = queue._mediation_signer.sign(encoded)
            if signature is None:
                queue._conn.rollback()
                return None
            changed = queue._conn.execute(
                """UPDATE tasks SET status='done',result=?,updated_at=?
                   WHERE id=? AND status='running' AND attempts=1""",
                (canonical_json(result).decode(), _utc_now(), task.id),
            )
            if changed.rowcount != 1:
                queue._conn.rollback()
                return None
            queue._conn.execute(
                """UPDATE task_restart_intents
                   SET completion_body=?,completion_signature=? WHERE task_id=?""",
                (encoded, signature, task.id),
            )
            queue._conn.commit()
            return VerifiedRestart(task.id, intent["intent_digest"], intent["boot_id"],
                                   requester["provider_key"], requester["bot_id"],
                                   requester["chat_id"], requester["sender_id"])
        except Exception:
            queue._conn.rollback()
            return None


def json_load(value):
    import json

    if not isinstance(value, (bytes, str)) or len(value) > 16384:
        raise ValueError("restart record unavailable")
    return json.loads(value)


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="microseconds")


def _verified_locked(queue, task_id: int, intent_digest: str, *,
                     for_notification: bool) -> VerifiedRestart | None:
    from .queue import _row_to_task

    if type(task_id) is not int or task_id <= 0 or not valid_digest(intent_digest):
        return None
    row = queue._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    intent = queue._conn.execute(
        "SELECT * FROM task_restart_intents WHERE task_id=?", (task_id,)
    ).fetchone()
    if (row is None or row["status"] != "done" or intent is None
            or intent["intent_digest"] != intent_digest
            or intent["completion_body"] is None or intent["completion_signature"] is None):
        return None
    task = _row_to_task(row)
    if not _human_restart(task):
        return None
    source = _source_current_locked(queue, task)
    if source is None:
        return None
    requester = source[1]
    arm_body = json_load(intent["arm_body"])
    completion = json_load(intent["completion_body"])
    result = task.result
    fingerprint = queue.execution_fingerprint(task)
    if (type(arm_body) is not dict or set(arm_body) != {
            "purpose", "version", "task_id", "boot_id", "execution_fingerprint",
            "requester", "armed_at_ms"
    } or arm_body["purpose"] != ARM_PURPOSE or arm_body["version"] != 1
            or arm_body["task_id"] != task_id or not valid_boot(arm_body["boot_id"])
            or arm_body["boot_id"] != intent["boot_id"]
            or arm_body["requester"] != requester
            or type(arm_body["armed_at_ms"]) is not int
            or arm_body["execution_fingerprint"] != fingerprint
            or digest(arm_body) != intent_digest
            or not queue._mediation_signer.verify(intent["arm_body"], intent["arm_signature"])):
        return None
    if (type(completion) is not dict or set(completion) != {
            "purpose", "version", "task_id", "intent_digest", "execution_fingerprint",
            "result_sha256", "completed_at_ms"
    } or completion["purpose"] != COMPLETION_PURPOSE or completion["version"] != 1
            or completion["task_id"] != task_id or completion["intent_digest"] != intent_digest
            or completion["execution_fingerprint"] != fingerprint
            or type(completion["completed_at_ms"]) is not int
            or completion["completed_at_ms"] < arm_body["armed_at_ms"]
            or completion["result_sha256"] != digest(result)
            or not queue._mediation_signer.verify(
                intent["completion_body"], intent["completion_signature"])):
        return None
    if (type(result) is not dict or result != {
            "status": "ok", "phase": "armed", "intent_digest": intent_digest
    } or not _mediation_current_locked(
        queue, row, at_ms=(completion["completed_at_ms"] if for_notification
                           else queue._clock_ms()), current_policy=not for_notification,
    )):
        return None
    return VerifiedRestart(task_id, intent_digest, intent["boot_id"],
                           requester["provider_key"], requester["bot_id"],
                           requester["chat_id"], requester["sender_id"])


def validate_completion(queue, task_id: int, intent_digest: str, *,
                        for_notification: bool = False) -> VerifiedRestart | None:
    with queue._lock:
        try:
            queue._conn.execute("BEGIN")
            verified = _verified_locked(queue, task_id, intent_digest,
                                        for_notification=for_notification)
            queue._conn.rollback()
            return verified
        except Exception:
            queue._conn.rollback()
            return None


def claim_physical(queue, task_id: int, intent_digest: str, boot_id: str) -> PhysicalClaim | None:
    if not valid_boot(boot_id):
        return None
    with queue._lock:
        try:
            queue._conn.execute("BEGIN IMMEDIATE")
            verified = _verified_locked(queue, task_id, intent_digest, for_notification=False)
            if verified is None or verified.boot_id != boot_id:
                queue._conn.rollback()
                return None
            claim_id = uuid.uuid4().hex
            changed = queue._conn.execute(
                """UPDATE task_restart_intents SET physical_state='attempting',physical_claim=?
                   WHERE task_id=? AND intent_digest=? AND boot_id=?
                     AND physical_state='unclaimed' AND physical_claim IS NULL""",
                (claim_id, task_id, intent_digest, boot_id),
            )
            if changed.rowcount != 1:
                queue._conn.rollback()
                return None
            queue._conn.commit()
            return PhysicalClaim(claim_id, verified)
        except Exception:
            queue._conn.rollback()
            return None


def refuse_physical(queue, task_id: int, intent_digest: str, boot_id: str) -> bool:
    if not valid_boot(boot_id):
        return False
    with queue._lock:
        try:
            queue._conn.execute("BEGIN IMMEDIATE")
            # A revoked current policy must still permit recording that no
            # physical effect began. Historical signed completion suffices.
            verified = _verified_locked(queue, task_id, intent_digest, for_notification=True)
            if verified is None or verified.boot_id != boot_id:
                queue._conn.rollback()
                return False
            changed = queue._conn.execute(
                """UPDATE task_restart_intents SET physical_state='refused'
                   WHERE task_id=? AND intent_digest=? AND boot_id=?
                     AND physical_state='unclaimed' AND physical_claim IS NULL""",
                (task_id, intent_digest, boot_id),
            )
            queue._conn.commit()
            return changed.rowcount == 1
        except Exception:
            queue._conn.rollback()
            return False


def finish_physical(queue, claim: PhysicalClaim, outcome: str) -> bool:
    if type(claim) is not PhysicalClaim or outcome not in {"requested", "refused", "unknown"}:
        return False
    with queue._lock:
        try:
            queue._conn.execute("BEGIN IMMEDIATE")
            changed = queue._conn.execute(
                """UPDATE task_restart_intents SET physical_state=?
                   WHERE task_id=? AND intent_digest=? AND boot_id=?
                     AND physical_state='attempting' AND physical_claim=?""",
                (outcome, claim.restart.task_id, claim.restart.intent_digest,
                 claim.restart.boot_id, claim.claim_id),
            )
            queue._conn.commit()
            return changed.rowcount == 1
        except Exception:
            queue._conn.rollback()
            return False


def recover(queue, new_boot_id: str) -> dict[str, int]:
    if not valid_boot(new_boot_id):
        return {"refused": 0, "unknown": 0}
    with queue._lock:
        try:
            queue._conn.execute("BEGIN IMMEDIATE")
            rows = queue._conn.execute(
                """SELECT task_id,intent_digest,physical_state FROM task_restart_intents
                   WHERE boot_id!=? AND physical_state IN ('unclaimed','attempting')
                     AND completion_body IS NOT NULL ORDER BY task_id LIMIT ?""",
                (new_boot_id, MAX_RESTART_ROWS + 1),
            ).fetchall()
            if len(rows) > MAX_RESTART_ROWS:
                raise RestartStateUnavailable("restart recovery capacity exceeded")
            refused = unknown = 0
            for row in rows:
                if _verified_locked(queue, row["task_id"], row["intent_digest"],
                                    for_notification=True) is None:
                    continue
                before = row["physical_state"]
                after = "refused" if before == "unclaimed" else "unknown"
                changed = queue._conn.execute(
                    """UPDATE task_restart_intents SET physical_state=?
                       WHERE task_id=? AND physical_state=?""",
                    (after, row["task_id"], before),
                ).rowcount
                if before == "unclaimed":
                    refused += changed
                else:
                    unknown += changed
            queue._conn.commit()
            queue._restart_boot_id = new_boot_id
            return {"refused": refused, "unknown": unknown}
        except Exception:
            queue._conn.rollback()
            raise RestartStateUnavailable("restart recovery unavailable") from None


def list_notices(queue, new_boot_id: str, limit: int = 32) -> tuple[VerifiedRestart, ...]:
    if not valid_boot(new_boot_id) or type(limit) is not int or not 1 <= limit <= 32:
        return ()
    with queue._lock:
        try:
            queue._conn.execute("BEGIN")
            rows = queue._conn.execute(
                """SELECT task_id,intent_digest FROM task_restart_intents
                   WHERE boot_id!=? AND completion_body IS NOT NULL
                     AND physical_state IN ('attempting','unknown','requested')
                     AND notice_state='unclaimed' ORDER BY task_id LIMIT ?""",
                (new_boot_id, limit),
            ).fetchall()
            offered = [_verified_locked(queue, row["task_id"], row["intent_digest"],
                                        for_notification=True) for row in rows]
            if any(item is None for item in offered):
                raise RestartStateUnavailable("restart notice receipt unavailable")
            found = tuple(offered)
            queue._conn.rollback()
            return found
        except Exception:
            queue._conn.rollback()
            raise RestartStateUnavailable("restart notices unavailable") from None


def claim_notice(queue, task_id: int, intent_digest: str, new_boot_id: str, *,
                 live_check) -> NoticeClaim | None:
    if not valid_boot(new_boot_id) or not callable(live_check):
        return None
    with queue._lock:
        try:
            queue._conn.execute("BEGIN IMMEDIATE")
            verified = _verified_locked(queue, task_id, intent_digest, for_notification=True)
            if verified is None or verified.boot_id == new_boot_id or live_check(verified) is not True:
                queue._conn.rollback()
                return None
            claim_id = uuid.uuid4().hex
            changed = queue._conn.execute(
                """UPDATE task_restart_intents SET notice_state='attempting',notice_claim=?
                   WHERE task_id=? AND intent_digest=? AND boot_id!=?
                     AND physical_state IN ('attempting','unknown','requested')
                     AND notice_state='unclaimed' AND notice_claim IS NULL""",
                (claim_id, task_id, intent_digest, new_boot_id),
            )
            if changed.rowcount != 1:
                queue._conn.rollback()
                return None
            queue._conn.commit()
            return NoticeClaim(claim_id, verified,
                               f"restart.notice:{task_id}:{verified.bot_id}:{verified.chat_id}")
        except Exception:
            queue._conn.rollback()
            return None


def finish_notice(queue, claim: NoticeClaim, outcome: str) -> bool:
    if type(claim) is not NoticeClaim or outcome not in {"sent", "failed", "unknown"}:
        return False
    with queue._lock:
        try:
            queue._conn.execute("BEGIN IMMEDIATE")
            changed = queue._conn.execute(
                """UPDATE task_restart_intents SET notice_state=?
                   WHERE task_id=? AND intent_digest=? AND notice_state='attempting'
                     AND notice_claim=?""",
                (outcome, claim.restart.task_id, claim.restart.intent_digest, claim.claim_id),
            )
            queue._conn.commit()
            return changed.rowcount == 1
        except Exception:
            queue._conn.rollback()
            return False


@dataclass(frozen=True, slots=True)
class RestartSourceTicket:
    body: dict
    signature: str

    def as_dict(self) -> dict:
        return {"body": dict(self.body), "signature": self.signature}


@dataclass(frozen=True, slots=True)
class VerifiedRestart:
    task_id: int
    intent_digest: str
    boot_id: str
    provider_key: str
    bot_id: int
    chat_id: int
    sender_id: int


@dataclass(frozen=True, slots=True)
class RestartArm(VerifiedRestart):
    pass


@dataclass(frozen=True, slots=True)
class PhysicalClaim:
    claim_id: str
    restart: VerifiedRestart


@dataclass(frozen=True, slots=True)
class NoticeClaim:
    claim_id: str
    restart: VerifiedRestart
    delivery_key: str


__all__ = ["ARM_PURPOSE", "COMPLETION_PURPOSE", "KIND", "MAX_RESTART_ROWS", "NoticeClaim",
           "PhysicalClaim", "PREVIEW", "RestartArm", "RestartSourceTicket", "SOURCE_PURPOSE",
           "SOURCE_PURPOSE_V1", "SOURCE_TTL_MS", "TITLE", "VerifiedRestart", "digest", "request_payload",
           "valid_boot", "valid_digest", "valid_requester"]
