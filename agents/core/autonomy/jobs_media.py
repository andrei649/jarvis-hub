"""Owner-bound scheduled media. No paths, remote references or implicit retries."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import re
import secrets
import time

from ..artifact_store import MAX_UPLOAD, resolve_blob
from ..env_config import env_flag, env_str

MAX_FILES = 8
MAX_TOTAL = 32 * 1024 * 1024
TIMEOUT_SETTING = "jobs.media_send_timeout_seconds"
_ID = re.compile(r"(?:ba-[a-f0-9]{32}|md-[a-f0-9]{12}|[a-f0-9]{32})")


def validate_media(action, options=None):
    if not isinstance(action, dict) or (options is not None and not isinstance(options, dict)):
        return ["action and options must be objects"]
    if "media_ids" not in action:
        return []
    ids = action["media_ids"]
    if (
        action.get("type") != "remind"
        or not isinstance(ids, list)
        or not 1 <= len(ids) <= MAX_FILES
        or any(not isinstance(item, str) or not _ID.fullmatch(item) for item in ids)
        or len(set(ids)) != len(ids)
    ):
        return ["media_ids requires 1..8 unique opaque artifact IDs on a reminder"]
    if action.get("channel", "telegram") != "telegram" or (options or {}).get(
        "deliver", ["telegram"]
    ) != ["telegram"]:
        return ["scheduled media supports only the configured Telegram owner"]
    return []


class MediaRefusal(ValueError):
    """Safe bounded refusal text; transport exceptions never become public reasons."""


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _action_identity(action, options):
    return _digest([action, (options or {}).get("deliver", ["telegram"])])


class ScheduledMedia:
    def __init__(self, runner):
        self.runner = runner
        self.store = runner.store
        self._tasks = set()
        with self.store._lock, self.store._conn:
            self.store._conn.execute(
                "CREATE TABLE IF NOT EXISTS job_media_bindings (job_id TEXT PRIMARY KEY, generation TEXT NOT NULL, data TEXT NOT NULL)"
            )
            self.store._conn.execute(
                "CREATE TABLE IF NOT EXISTS job_media_receipts (id TEXT PRIMARY KEY, job_id TEXT NOT NULL, generation TEXT NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL, created REAL NOT NULL)"
            )

    def timeout(self):
        getter = getattr(self.runner._orch, "get_setting", lambda key, default=None: default)
        value = getter(TIMEOUT_SETTING, 300)
        if type(value) is not int or not 1 <= value <= 300:
            raise MediaRefusal("media deadline must be an integer from 1 to 300 seconds")
        return value

    def _destination(self):
        orch = self.runner._orch
        adapter = (getattr(orch, "channels", None) or {}).get("telegram")
        if adapter is None or not all(
            callable(getattr(adapter, method, None))
            for method in ("send_media", "send_scheduled_text")
        ):
            raise MediaRefusal("configured Telegram adapter does not support media")
        getter = getattr(orch, "get_setting", lambda key, default=None: default)
        owner = str(
            env_str("AUTONOMY_OWNER_CHAT_ID", "") or getter("autonomy.owner_chat_id", "") or ""
        ).strip()
        if not re.fullmatch(r"-?[1-9][0-9]{0,19}", owner):
            raise MediaRefusal("a Telegram owner chat must be configured")
        token, endpoint = getattr(adapter, "token", ""), getattr(adapter, "api_base", "")
        if not token or not endpoint:
            raise MediaRefusal("Telegram configuration is unavailable")
        # This fingerprint stays in the private journal, never a user-visible token/status.
        return {"chat_id": int(owner), "bot": _digest([token, endpoint])}, adapter

    def _read(self, ids):
        blobs, descriptors, total = [], [], 0
        for item_id in ids:
            if item_id.startswith("ba-") and not env_flag("JARVIS_BINARY_ARTIFACTS"):
                raise MediaRefusal("binary attachments disabled")
            if item_id.startswith("md-") and not env_flag("JARVIS_MEDIA_CATALOG"):
                raise MediaRefusal("media catalog disabled")
            try:
                meta, data = resolve_blob(item_id)
            except (ValueError, OSError):
                raise MediaRefusal("scheduled media is unavailable or invalid") from None
            total += len(data)
            if len(data) > MAX_UPLOAD or total > MAX_TOTAL:
                raise MediaRefusal("scheduled media exceeds 16 MiB per file or 32 MiB total")
            descriptors.append(
                {
                    "id": item_id,
                    "mime": meta["mime"],
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
            blobs.append(data)
        return descriptors, blobs

    def prepare(self, action, options=None):
        errors = validate_media(action, options)
        if errors:
            raise MediaRefusal(errors[0])
        if "media_ids" not in action:
            return None
        self.timeout()
        destination, _ = self._destination()
        descriptors, _ = self._read(action["media_ids"])
        return {
            "identity": _action_identity(action, options),
            "destination": destination,
            "files": descriptors,
        }

    def bind(self, job, binding):
        with self.store._lock, self.store._conn:
            self.store._conn.execute(
                "UPDATE job_media_receipts SET status='unknown' WHERE job_id=? AND status IN ('prepared','sending')",
                (job.id,),
            )
            if binding is None:
                self.store._conn.execute("DELETE FROM job_media_bindings WHERE job_id=?", (job.id,))
            else:
                self.store._conn.execute(
                    "INSERT OR REPLACE INTO job_media_bindings VALUES (?,?,?)",
                    (job.id, secrets.token_hex(16), json.dumps(binding)),
                )
            self.store._conn.execute(
                "UPDATE job_media_receipts SET status='discarded' WHERE job_id=? AND status='held'",
                (job.id,),
            )

    def remove(self, job_id):
        with self.store._lock, self.store._conn:
            self.store._conn.execute("DELETE FROM job_media_bindings WHERE job_id=?", (job_id,))
            self.store._conn.execute("DELETE FROM job_media_receipts WHERE job_id=?", (job_id,))

    def _binding(self, job_id):
        with self.store._lock:
            row = self.store._conn.execute(
                "SELECT * FROM job_media_bindings WHERE job_id=?", (job_id,)
            ).fetchone()
        if row is None:
            raise MediaRefusal("media job needs an explicit action re-save to authorize delivery")
        return row["generation"], json.loads(row["data"])

    def _receipt(self, receipt_id):
        with self.store._lock:
            row = self.store._conn.execute(
                "SELECT * FROM job_media_receipts WHERE id=?", (receipt_id,)
            ).fetchone()
        return {**dict(row), "data": json.loads(row["data"])} if row else None

    def _state(self, receipt_id, status, **fields):
        with self.store._lock, self.store._conn:
            row = self.store._conn.execute(
                "SELECT data FROM job_media_receipts WHERE id=?", (receipt_id,)
            ).fetchone()
            if row is None:
                return
            data = {**json.loads(row["data"]), **fields}
            self.store._conn.execute(
                "UPDATE job_media_receipts SET status=?, data=? WHERE id=?",
                (status, json.dumps(data), receipt_id),
            )

    def public(self, job_id):
        with self.store._lock:
            row = self.store._conn.execute(
                "SELECT status,data FROM job_media_receipts WHERE job_id=? ORDER BY created DESC, rowid DESC LIMIT 1",
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        data = json.loads(row["data"])
        return {
            "status": row["status"],
            "sent": data["sent"],
            "total": data["total"],
            "reason": data.get("reason", ""),
        }

    def _check(self, job_id, generation, binding, deadline=None):
        from .. import estop

        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("media deadline expired")
        if estop.check_paused("job-media:" + job_id, __import__("logging").getLogger(__name__)):
            raise MediaRefusal("emergency stop engaged")
        job = self.store.get(job_id)
        if job is None or not job.enabled or job.paused_reason:
            raise MediaRefusal("media job disabled, paused or deleted")
        current_generation, _ = self._binding(job_id)
        if (
            current_generation != generation
            or _action_identity(job.action, job.options) != binding["identity"]
        ):
            raise MediaRefusal("media job authorization changed; re-save its action")
        destination, adapter = self._destination()
        if destination != binding["destination"]:
            raise MediaRefusal("media recipient or bot changed; re-save the action")
        return adapter

    @contextlib.contextmanager
    def _gate(self, job_id):
        from ..vault import _file_lock

        stripe = int(hashlib.sha256(job_id.encode()).hexdigest()[:8], 16) % 64
        with _file_lock(
            self.store._path.with_name(self.store._path.name + f".media-{stripe}"), timeout=0
        ):
            yield

    def _blocked(self, job_id, generation):
        with self.store._lock:
            row = self.store._conn.execute(
                "SELECT id,status FROM job_media_receipts WHERE job_id=? AND generation=? AND status IN ('prepared','sending','partial','unknown') LIMIT 1",
                (job_id, generation),
            ).fetchone()
        if row:
            if row["status"] in ("prepared", "sending"):
                self._state(
                    row["id"],
                    "unknown",
                    reason="interrupted delivery; review channel before reauthorizing",
                )
            self.store.update(
                job_id,
                paused_reason="Media delivery unresolved; review channel, re-save action, then resume",
                last_delivery_status="unknown",
            )
            raise MediaRefusal("previous media delivery unresolved; no automatic replay")

    async def deliver(self, job, text):
        deadline = time.monotonic() + self.timeout()
        with self._gate(job.id):
            generation, binding = self._binding(job.id)
            if _action_identity(job.action, job.options) != binding[
                "identity"
            ] or text != job.action.get("message"):
                raise MediaRefusal("media job snapshot or text authorization changed")
            self._blocked(job.id, generation)
            self._check(job.id, generation, binding, deadline)
            receipt_id = secrets.token_hex(16)
            held = self.runner.quiet_hours() and not (
                job.action.get("urgent") and self.runner._spend_interrupt(job)
            )
            data = {"text": text, "sent": 0, "total": len(binding["files"]) + 1, "reason": ""}
            with self.store._lock, self.store._conn:
                self.store._conn.execute(
                    "INSERT INTO job_media_receipts VALUES (?,?,?,?,?,?)",
                    (
                        receipt_id,
                        job.id,
                        generation,
                        "held" if held else "prepared",
                        json.dumps(data),
                        time.time(),
                    ),
                )
                self.store._conn.execute(
                    "UPDATE job_media_receipts SET status='discarded' WHERE job_id=? AND status='held' AND id NOT IN (SELECT id FROM job_media_receipts WHERE job_id=? AND status='held' ORDER BY created DESC LIMIT 20)",
                    (job.id, job.id),
                )
                self.store._conn.execute(
                    "DELETE FROM job_media_receipts WHERE job_id=? AND (status IN ('sent','failed','discarded') OR (generation != ? AND status IN ('unknown','partial'))) AND id NOT IN (SELECT id FROM job_media_receipts WHERE job_id=? ORDER BY created DESC LIMIT 200)",
                    (job.id, generation, job.id),
                )
            if held:
                self.store.update(job.id, last_delivery_status="held")
                return "media held until quiet hours end"
            return await self._run(receipt_id, generation, binding, deadline)

    def _failure(self, receipt_id, reason):
        row = self._receipt(receipt_id)
        if row is None:
            return
        status = (
            "unknown"
            if row["status"] in ("sending", "unknown")
            else "partial"
            if row["data"]["sent"]
            else "failed"
        )
        self._state(receipt_id, status, reason=reason)
        job = self.store.get(row["job_id"])
        if job:
            fields = {"last_delivery_status": status}
            if status in ("partial", "unknown"):
                fields["paused_reason"] = (
                    "Media delivery unresolved; review channel, re-save action, then resume"
                )
            self.store.update(job.id, **fields)

    async def _run(self, receipt_id, generation, binding, deadline):
        row = self._receipt(receipt_id)
        abandoned = False

        async def work():
            descriptors, blobs = await asyncio.to_thread(
                self._read, [file["id"] for file in binding["files"]]
            )
            if descriptors != binding["files"]:
                raise MediaRefusal("media contents changed; re-save the action")
            for index in range(len(blobs) + 1):
                adapter = self._check(row["job_id"], generation, binding, deadline)
                from ..channels.send_rate_limit import allow_send

                if not allow_send("telegram"):
                    raise MediaRefusal("Telegram send rate exceeded")
                sink = getattr(self.runner._orch, "action_audit", None)
                fields = {
                    "job_id": row["job_id"],
                    "delivery_id": receipt_id,
                    "index": index,
                    "kind": "media" if index < len(blobs) else "text",
                }
                if sink is None or sink.log("job.media.send", fields) is None:
                    raise MediaRefusal("delivery audit unavailable")
                self._check(row["job_id"], generation, binding, deadline)
                self._state(receipt_id, "sending")
                if index < len(blobs):
                    file = binding["files"][index]
                    ok = await adapter.send_media(
                        blobs[index],
                        mime=file["mime"],
                        filename=file["id"],
                        chat_id=binding["destination"]["chat_id"],
                    )
                else:
                    ok = await adapter.send_scheduled_text(
                        row["data"]["text"], chat_id=binding["destination"]["chat_id"]
                    )
                if abandoned:
                    raise asyncio.CancelledError
                self._check(row["job_id"], generation, binding, deadline)
                if not ok:
                    raise MediaRefusal("Telegram did not acknowledge delivery")
                self._state(receipt_id, "prepared", sent=index + 1)
            self._state(receipt_id, "sent")
            self.store.update(row["job_id"], last_delivery_status="sent")

        task = asyncio.create_task(work())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        try:
            while not task.done():
                self._check(row["job_id"], generation, binding, deadline)
                await asyncio.wait({task}, timeout=min(0.05, max(0, deadline - time.monotonic())))
            await task
        except BaseException as exc:
            abandoned = True
            task.cancel()
            # A cancelled transport may already have reached Telegram; never call it unsent.
            reason = (
                "media total delivery deadline expired"
                if isinstance(exc, TimeoutError)
                else "media delivery cancelled"
                if isinstance(exc, asyncio.CancelledError)
                else str(exc)
                if isinstance(exc, MediaRefusal)
                else "media delivery failed"
            )
            self._failure(receipt_id, reason)

            def consume(finished):
                with contextlib.suppress(BaseException):
                    finished.result()

            task.add_done_callback(consume)
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise MediaRefusal(reason) from None
        return f"media delivered ({len(binding['files'])} files and text)"

    async def flush_held(self):
        from .. import estop

        if self.runner.quiet_hours() or estop.check_paused(
            "jobs-media-held", __import__("logging").getLogger(__name__)
        ):
            return 0
        with self.store._lock:
            rows = self.store._conn.execute(
                "SELECT r.id,r.job_id,r.generation FROM job_media_receipts r JOIN jobs j ON j.id=r.job_id WHERE r.status='held' AND j.enabled=1 AND (j.paused_reason IS NULL OR j.paused_reason='') ORDER BY r.created LIMIT 100"
            ).fetchall()
        sent = 0
        for row in rows:
            try:
                deadline = time.monotonic() + self.timeout()
                with self._gate(row["job_id"]):
                    current = self._receipt(row["id"])
                    if (
                        current is None
                        or current["status"] != "held"
                        or current["job_id"] != row["job_id"]
                        or current["generation"] != row["generation"]
                    ):
                        continue
                    generation, binding = self._binding(row["job_id"])
                    if generation != row["generation"] or self.store.get(row["job_id"]) is None:
                        self._state(row["id"], "discarded", reason="job authorization changed")
                        continue
                    job = self.store.get(row["job_id"])
                    if not job.enabled or job.paused_reason:
                        continue
                    self._blocked(row["job_id"], generation)
                    self._check(row["job_id"], generation, binding, deadline)
                    self._state(row["id"], "prepared")
                    await self._run(row["id"], generation, binding, deadline)
                    sent += 1
            except Exception as exc:
                receipt = self._receipt(row["id"])
                if receipt and receipt["status"] == "held":
                    self._failure(
                        row["id"],
                        str(exc) if isinstance(exc, MediaRefusal) else "held media delivery failed",
                    )
                # Terminal/ambiguous receipts are never selected again as held work.
                break
        return sent
