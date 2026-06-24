"""
node_mesh.py — H12.17 Governed node mesh (execution nodes).

Phone/desktop devices register as *execution nodes* that may run ONLY
capability-scoped, approved actions; the home GPU stays the brain. Unifies the
Tauri desktop client (H11.1, host seam) and the mic-satellite split (H12.8)
under one governance model built on the H17.3 capability broker + kill-switch:

  register_node → mint a capability-scoped token (the node can't escalate —
                  H17.3 tokens are read-only and grant only the declared caps)
  dispatch      → authorize (kill-switch + capability) → enqueue an ask-tier
                  governed task; nothing runs on the node until approved
  execute       → RE-authorize at action time (token may have expired/been
                  revoked, kill-switch may be engaged), then hand off to the node
                  client (the actual on-device run is the host seam)

Pure-Python and offline-testable; the capability broker, kill-switch and enqueue
sink are injected.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from .autonomy.dry_run import preview_task
from .security.capability import authorize as _authorize

logger = logging.getLogger("jarvis.node_mesh")

KIND = "node.dispatch"
_RISK_TIER = 2   # remote on-device action → external → ASK


class NodeMesh:
    """Registry of governed execution nodes + capability-gated dispatch."""

    def __init__(self, capability_broker=None, kill_switch=None, enqueue=None,
                 agent: str = "jarvis", audit=None, token_ttl: float = 86_400.0,
                 kernel=None) -> None:
        self._broker = capability_broker
        self._kill = kill_switch
        self._enqueue = enqueue
        self.agent = agent
        self._audit = audit
        self._ttl = float(token_ttl)
        self._nodes: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._kernel = kernel   # ORIZONT-24 K1: bound kernel.authorize (default-off)

    # ── registry ─────────────────────────────────────────────────────────────

    def register_node(self, node_id: str, capabilities, meta: Optional[dict] = None) -> dict:
        node_id = str(node_id)
        caps = sorted({str(c) for c in (capabilities or []) if str(c).strip()})
        token_id = ""
        if self._broker is not None:
            token_id = self._broker.issue(
                caps, source=f"node:{node_id}", task_id=node_id, ttl=self._ttl)["id"]
        rec = {"id": node_id, "capabilities": caps, "token_id": token_id,
               "meta": meta or {}, "registered_at": time.time()}
        with self._lock:
            old = self._nodes.get(node_id)
            if old and old.get("token_id") and self._broker is not None:
                self._broker.revoke(old["token_id"])   # re-register → fresh token
            self._nodes[node_id] = rec
        self._record("node.register", node_id, capabilities=caps)
        out = self._public(rec)
        out["token_issued"] = bool(token_id)
        return out

    def nodes(self) -> "list[dict]":
        with self._lock:
            return [self._public(r) for r in self._nodes.values()]

    def get(self, node_id: str) -> Optional[dict]:
        with self._lock:
            r = self._nodes.get(str(node_id))
        return self._public(r) if r else None

    def revoke(self, node_id: str) -> bool:
        with self._lock:
            r = self._nodes.pop(str(node_id), None)
        if r and r.get("token_id") and self._broker is not None:
            self._broker.revoke(r["token_id"])
        return r is not None

    # ── dispatch ─────────────────────────────────────────────────────────────

    def dispatch(self, node_id: str, capability: str, action: str = "",
                 payload: Optional[dict] = None) -> dict:
        node_id, capability = str(node_id), str(capability)
        title = f"Node {node_id}: {capability}"
        task_payload = {"node": node_id, "capability": capability,
                        "action": str(action or ""), "args": payload or {},
                        "target": node_id}
        # ORIZONT-24 K1: when the kernel is enabled it composes the SAME capability
        # nucleus (node presents its real token) + policy + audit; execute()-time
        # re-authorization stays as defense-in-depth. Default-off → today's
        # _authorize path runs, byte-identical to before.
        autonomy_level = "ask"
        kernel_ran = False
        # Keep the kernel import and its uses in ONE block so the names are always
        # bound before use (a split import/use trips CodeQL's may-be-uninitialized).
        if self._kernel is not None:
            from .kernel import Action, Capability, Verdict, kernel_enabled
            if kernel_enabled():
                kernel_ran = True
                with self._lock:
                    rec = self._nodes.get(node_id)
                if rec is None:
                    return {"ok": False, "reason": "unknown_node"}
                decision = self._kernel(
                    Action(kind=KIND, agent=self.agent, title=title, payload=task_payload,
                           scope=f"node:{node_id}", origin="generated"),
                    Capability(token_id=rec.get("token_id", ""), name=capability))
                if decision.verdict is Verdict.DENY:
                    return {"ok": False, "reason": decision.reason}
                if decision.verdict is Verdict.GRANT:
                    autonomy_level = "act"
        if not kernel_ran:
            # kernel disabled or not bound → today's capability check, unchanged.
            auth = self._authorize(node_id, capability)
            if not auth.get("allowed"):
                return {"ok": False, "reason": auth.get("reason", "denied")}
        preview = preview_task({"kind": KIND, "title": title,
                                "payload": task_payload, "risk_tier": _RISK_TIER})
        if self._enqueue is None:
            return {"ok": True, "queued": False, "kind": KIND,
                    "payload": task_payload, "preview": preview}
        try:
            task_id = self._enqueue(self.agent, KIND, title, payload=task_payload,
                                    risk_tier=_RISK_TIER, autonomy_level=autonomy_level,
                                    origin="generated")
        except Exception:
            logger.warning("node dispatch enqueue failed", exc_info=True)
            return {"ok": False, "reason": "enqueue_failed"}
        self._record("node.dispatch", node_id, capability=capability)
        return {"ok": True, "queued": True, "task_id": task_id, "kind": KIND,
                "preview": preview}

    async def execute(self, task) -> dict:
        payload = getattr(task, "payload", None) or {}
        node_id = payload.get("node")
        capability = payload.get("capability")
        # Re-authorize at action time — token may have expired/been revoked, or
        # the kill-switch engaged, since the task was queued.
        auth = self._authorize(node_id, capability)
        if not auth.get("allowed"):
            return {"status": "failed", "reason": auth.get("reason", "denied"), "node": node_id}
        self._record("node.execute", node_id, capability=capability)
        return {"status": "ok", "node": node_id, "capability": capability,
                "dispatch": {"status": "deferred",
                             "note": "handed to node client — host seam"}}

    # ── internals ────────────────────────────────────────────────────────────

    def _authorize(self, node_id: str, capability: str) -> dict:
        with self._lock:
            rec = self._nodes.get(str(node_id))
        if rec is None:
            return {"allowed": False, "reason": "unknown_node"}
        if self._broker is None:
            return {"allowed": False, "reason": "capability_broker_unavailable"}
        if self._kill is not None:
            return _authorize(self._broker, self._kill, rec["token_id"], capability,
                              scope=f"node:{node_id}")
        ok = self._broker.check(rec["token_id"], capability)
        return {"allowed": ok, "reason": "" if ok else "no_valid_capability"}

    @staticmethod
    def _public(rec: dict) -> dict:
        return {k: v for k, v in rec.items() if k != "token_id"}

    def _record(self, action: str, why: str, **meta) -> None:
        if self._audit is None:
            return
        try:
            if hasattr(self._audit, "record"):
                self._audit.record(actor="node_mesh", action=action, why=why, metadata=meta)
            elif hasattr(self._audit, "log"):
                self._audit.log({"event": action, "why": why, **meta})
        except Exception:  # pragma: no cover - best-effort
            pass
