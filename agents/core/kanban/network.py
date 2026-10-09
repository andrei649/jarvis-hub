"""One approved, DNS-pinned URL hop for a Kanban attachment."""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import threading
import time
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from agents.core import estop
from agents.core.autonomy.executor import ExecutionGuardDeclined
from agents.core.autonomy.jobs_url import screen_url
from agents.core.autonomy.queue import TaskQueue
from agents.core.http_client import PluginHTTPClient
from agents.core.kernel import Action, Verdict, kernel_enabled

from .context import KanbanContext, current_context, kanban_scope
from .upstream import kanban_db as kb
from .upstream.compat import require_scoped_path

PLUGIN = "kanban-attachments"
MAX_HOPS = 5
FAILURE = "kanban_url_fetch_failed"


class _Declined(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _Claim:
    def __init__(self, fingerprint: str):
        self.fingerprint = fingerprint
        self.active = True
        self.lock = threading.Lock()

    def consume(self, fingerprint: str) -> bool:
        with self.lock:
            active, self.active = self.active, False
            return active and fingerprint == self.fingerprint


class _StrictClient(PluginHTTPClient):
    def __init__(self, check, **kwargs):
        super().__init__(PLUGIN, **kwargs)
        self._check = check

    def _enforce_kernel(self, method, url, host):
        self._check(method, url)


def _digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class NetworkAttachmentAdapter:
    PLUGIN = PLUGIN

    def __init__(self, orch, *, home=None, resolver=None, transport_factory=None):
        self.orch = orch
        self.home = Path(home) if home is not None else None
        self.resolver = resolver
        self.transport_factory = transport_factory
        self._claim = contextvars.ContextVar("kanban_url_claim", default=None)

    @property
    def worker(self):
        return getattr(self.orch, "autonomy", None)

    @property
    def queue(self):
        return getattr(self.orch, "autonomy_queue", None)

    @property
    def redact(self):
        return getattr(getattr(self.orch, "secret_broker", None), "redact", None)

    def matches(self, task) -> bool:
        payload = getattr(task, "payload", None)
        return (getattr(task, "kind", None) == "plugin.egress"
                and isinstance(payload, dict) and payload.get("plugin") == PLUGIN)

    def _available(self):
        from agents.core.plugin_gate import BUILTIN_PLUGINS

        get = getattr(self.orch, "get_setting", None)
        if (not callable(get) or get("llm.kanban_network_attachments", False) is not True
                or get("llm.kanban", False) is not True
                or get("llm.tool_loop_enabled", False) is not True):
            raise _Declined("configuration_changed")
        worker, queue = self.worker, self.queue
        gate = getattr(self.orch, "permission_gate", None)
        manifests = gate.plugins if gate is not None else BUILTIN_PLUGINS
        manifest = manifests.get(PLUGIN)
        if manifest is None or not manifest.enabled:
            raise _Declined("configuration_changed")
        if (worker is None or not isinstance(queue, TaskQueue) or worker.queue is not queue
                or queue.mediation_mode != "enforce"
                or not kernel_enabled()):
            raise _Declined("enforced_mediation_unavailable")
        signer = getattr(worker, "_mediation_signer", None)
        if (not callable(getattr(worker, "govern_enqueue", None))
                or not callable(getattr(worker, "execution_allowed", None))
                or not callable(getattr(worker, "kernel_gate", None))
                or not callable(self.redact) or not callable(getattr(signer, "sign", None))):
            raise _Declined("enforced_mediation_unavailable")
        if estop.is_engaged() or worker._halted():
            raise _Declined("estop_engaged")

    def _screen(self, url):
        return screen_url(url, self.redact)

    def _identity(self, payload):
        self._available()
        if (not isinstance(payload, dict)
                or set(payload) != {"plugin", "method", "url", "representation", "attachment"}
                or payload["plugin"] != PLUGIN or payload["method"] != "GET"
                or payload["representation"] != "binary-identity"):
            raise _Declined("dispatch_changed")
        att = payload["attachment"]
        if (not isinstance(att, dict) or set(att) != {"board", "task_id", "profile", "session_id",
                                                    "run_id", "filename", "content_type", "hop",
                                                    "parent_queue_id", "parent_sha256"}
                or not all(isinstance(att[k], str) and att[k] for k in
                           ("board", "task_id", "profile", "filename"))
                or att["session_id"] is not None and not isinstance(att["session_id"], str)
                or att["run_id"] is not None and (type(att["run_id"]) is not int or att["run_id"] < 1)
                or att["content_type"] is not None and not isinstance(att["content_type"], str)
                or type(att["hop"]) is not int or not 0 <= att["hop"] <= MAX_HOPS
                or (att["hop"] == 0) != (att["parent_queue_id"] is None)
                or (att["hop"] == 0) != (att["parent_sha256"] is None)):
            raise _Declined("dispatch_changed")
        self._screen(payload["url"])
        if kb._safe_attachment_name(att["filename"]) != att["filename"]:
            raise _Declined("dispatch_changed")
        if att["hop"]:
            parent = self.queue.get(att["parent_queue_id"])
            result = getattr(parent, "result", None)
            if (parent is None or parent.status != "done" or not self.matches(parent)
                    or _digest(parent.payload) != att["parent_sha256"]
                    or parent.payload["attachment"]["hop"] + 1 != att["hop"]
                    or {k: v for k, v in parent.payload["attachment"].items()
                        if k not in {"hop", "parent_queue_id", "parent_sha256"}}
                       != {k: v for k, v in att.items()
                           if k not in {"hop", "parent_queue_id", "parent_sha256"}}
                    or not isinstance(result, dict) or result.get("status") != "approval_required"
                    or result.get("redirect_sha256") != _digest(payload)):
                raise _Declined("dispatch_changed")
        return att

    def _board_current(self, att):
        home = self.home
        if home is None:
            raise _Declined("configuration_changed")
        with (kanban_scope(KanbanContext(home, att["profile"], board=att["board"], can_mutate=True)),
              kb.connect_closing(board=att["board"]) as conn):
            task = kb.get_task(conn, att["task_id"])
            if task is None or (att["run_id"] is not None and
                                (task.current_run_id != att["run_id"]
                                 or task.status not in {"running", "review"}
                                 or task.assignee != att["profile"])):
                raise _Declined("board_run_changed")

    def _enqueue(self, payload):
        self._identity(payload)
        self._board_current(payload["attachment"])
        qid = self.worker.govern_enqueue(
            agent=payload["attachment"]["profile"], kind="plugin.egress",
            title="Kanban URL attachment approval", payload=payload,
            risk_tier=3, autonomy_level="ask", origin="generated",
        )
        return {"ok": True, "status": "approval_required", "queue_id": qid}

    def submit(self, args) -> dict:
        try:
            self._available()
            context = current_context()
            if (context is None or not context.can_mutate or context.delegated
                    or self.home is None or context.home.resolve() != self.home.resolve()
                    or not isinstance(args, dict)
                    or set(args) - {"task_id", "board", "url", "filename", "title", "content_type"}):
                raise _Declined("scope_required")
            board = args.get("board") or context.board
            tid = args.get("task_id") or context.task_id
            if (not isinstance(tid, str) or not tid or board != context.board
                    or context.task_id is not None and
                    (context.task_id != tid or context.run_id is None)):
                raise _Declined("scope_required")
            url = self._screen(args.get("url"))
            filename = args.get("filename") or args.get("title")
            if filename is None:
                filename = unquote(urlsplit(url).path.rsplit("/", 1)[-1]).strip() or "download"
            filename = kb._safe_attachment_name(filename)
            ct = args.get("content_type")
            if ct is not None and (not isinstance(ct, str) or len(ct) > 255):
                raise _Declined("invalid_attachment")
            att = {"board": board, "task_id": tid, "profile": context.profile,
                   "session_id": context.session_id, "run_id": context.run_id,
                   "filename": filename, "content_type": ct, "hop": 0,
                   "parent_queue_id": None, "parent_sha256": None}
            payload = {"plugin": PLUGIN, "method": "GET", "url": url,
                       "representation": "binary-identity", "attachment": att}
            return self._enqueue(payload)
        except Exception:
            return {"ok": False, "reason": "kanban_url_refused"}

    def guard(self, task):
        self._claim.set(None)
        if not self.matches(task):
            return self.worker.execution_allowed(task)
        try:
            att = self._identity(task.payload)
            if task.agent != att["profile"]:
                raise _Declined("dispatch_changed")
            self._board_current(att)
            if not self.worker.execution_allowed(task):
                return False
            fingerprint = TaskQueue.execution_fingerprint(task)
            if not fingerprint:
                return False
            self._claim.set(_Claim(fingerprint))
            return True
        except _Declined as exc:
            raise ExecutionGuardDeclined(exc.reason) from None
        except Exception:
            return False

    def _check(self, task, fingerprint):
        att = self._identity(task.payload)
        if task.agent != att["profile"]:
            raise _Declined("dispatch_changed")
        if (self.worker._halted(task.agent)
                or (task.mediation_scope and self.worker._halted(task.mediation_scope))):
            raise _Declined("estop_engaged")
        self._board_current(att)
        if not self.queue.validate_mediated_execution(task, fingerprint):
            raise _Declined("mediation_execution_required")
        decision = self.worker.kernel_gate(Action(
            kind="plugin.egress", agent=task.agent, title="Kanban URL attachment GET",
            payload=task.payload, origin=task.origin,
        ))
        if getattr(decision, "verdict", None) not in {Verdict.GRANT, Verdict.QUEUE}:
            raise _Declined("kernel_denied")
        return att

    def _publish(self, task, fingerprint, data, content_type):
        att = task.payload["attachment"]
        with (kanban_scope(KanbanContext(self.home, att["profile"], board=att["board"], can_mutate=True)),
              kb.connect_closing(board=att["board"]) as conn, kb.write_txn(conn)):
            # The donor store nests a non-nestable transaction. Its filename,
            # path and event helpers are reused here inside the run check's lock.
            self._check(task, fingerprint)
            current = kb.get_task(conn, att["task_id"])
            if current is None or (att["run_id"] is not None and
                                   (current.current_run_id != att["run_id"]
                                    or current.status not in {"running", "review"}
                                    or current.assignee != att["profile"])):
                raise _Declined("board_run_changed")
            directory = require_scoped_path(kb.task_attachments_dir(att["task_id"], board=att["board"]))
            directory.mkdir(parents=True, exist_ok=True)
            path = kb._collision_free_path(directory, att["filename"])
            try:
                path.write_bytes(data)
                now = int(time.time())
                cursor = conn.execute(
                    "INSERT INTO task_attachments (task_id,filename,stored_path,content_type,size,uploaded_by,created_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (att["task_id"], path.name, str(path.resolve()), content_type,
                     len(data), "agent", now),
                )
                kb._append_event(conn, att["task_id"], "attached",
                                 {"filename": path.name, "size": len(data), "by": "agent"})
                self._check(task, fingerprint)
                return int(cursor.lastrowid)
            except BaseException:
                path.unlink(missing_ok=True)
                raise

    async def execute(self, task):
        claim = self._claim.get()
        self._claim.set(None)
        fingerprint = TaskQueue.execution_fingerprint(task)
        if (not self.matches(task) or not isinstance(claim, _Claim) or not fingerprint
                or not claim.consume(fingerprint)):
            return {"status": "refused", "reason": "kanban_url_execution_claim_required"}
        phase = "preflight"
        try:
            self._check(task, fingerprint)

            def dial(method, url):
                nonlocal phase
                if method != "GET" or url != task.payload["url"]:
                    raise _Declined("dispatch_changed")
                self._check(task, fingerprint)
                phase = "dialled"

            client = _StrictClient(dial, resolver=self.resolver,
                                   transport_factory=self.transport_factory)
            try:
                async with asyncio.timeout(30):
                    async with client.stream("GET", task.payload["url"], follow_redirects=False,
                                             headers={"Accept-Encoding": "identity"}) as response:
                        self._check(task, fingerprint)
                        if response.status_code in {301, 302, 303, 307, 308}:
                            att = task.payload["attachment"]
                            location = response.headers.get("location")
                            if not location or att["hop"] >= MAX_HOPS:
                                raise _Declined("redirect_limit")
                            destination = self._screen(urljoin(task.payload["url"], location))
                            child = {**task.payload, "url": destination,
                                     "attachment": {**att, "hop": att["hop"] + 1,
                                                    "parent_queue_id": task.id,
                                                    "parent_sha256": _digest(task.payload)}}
                            # A successor hop is a new ASK row. The parent result binds
                            # the exact destination before that row is proposed.
                            self._check(task, fingerprint)
                            qid = self.worker.govern_enqueue(
                                agent=att["profile"], kind="plugin.egress",
                                title="Kanban URL redirect approval", payload=child,
                                risk_tier=3, autonomy_level="ask", origin="generated",
                            )
                            return {"status": "approval_required", "queue_id": qid,
                                    "redirect_sha256": _digest(child)}
                        if not 200 <= response.status_code < 300:
                            raise ValueError("HTTP failure")
                        if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
                            raise ValueError("encoded representation")
                        body = bytearray()
                        async for chunk in response.aiter_raw():
                            if len(body) + len(chunk) > kb.KANBAN_ATTACHMENT_MAX_BYTES:
                                raise ValueError("attachment too large")
                            body.extend(chunk)
                        self._check(task, fingerprint)
                        content_type = task.payload["attachment"]["content_type"] or response.headers.get("content-type")
                        attachment_id = self._publish(task, fingerprint, bytes(body), content_type)
                        return {"status": "ok", "attachment_id": attachment_id,
                                "size": len(body), "identity": task.payload}
            finally:
                await client.close()
        except asyncio.CancelledError:
            raise
        except _Declined as exc:
            return {"status": "refused" if phase == "preflight" else "failed",
                    "reason": exc.reason if phase == "preflight" else "withheld_after_fetch"}
        except Exception:
            return {"status": "failed", "reason": FAILURE}
