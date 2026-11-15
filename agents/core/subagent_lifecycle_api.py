"""Public plugin & extension lifecycle API for sub-agent delegation (H650).

Exposes :class:`SubagentLifecycleAPI` as the single stable, host-governed interface for
plugins, internal workflows, and specialist extensions to spawn, batch, list, inspect,
steer, stop, and collect isolated sub-agents without importing ``delegate_tool`` or
touching private :class:`~agents.core.subagents.SubAgentManager` attributes.

Security invariants enforced by construction:
1. **Strict privilege non-escalation**: every child's tool allowlist is intersected with
   the caller's ``parent_offer`` and stripped of :data:`DELEGATE_BLOCKED_CAPABILITIES`
   via :func:`child_tool_allowlist`. Requesting any tool outside ``parent_offer`` or in
   the blocked capability set raises :class:`SubagentLifecycleError`
   (``privilege_escalation_refused``).
2. **No recursive sub-agent fan-out**: calls from inside a running child
   (:func:`current_spawn_id` set) are refused as ``delegation_blocked_for_subagents``.
3. **Session & parent ownership isolation**: ``list``, ``get``, ``steer``, ``stop``, and
   ``collect`` operate strictly on children spawned under this API's ``(parent_agent,
   session_id)`` scope; foreign children are invisible and refused with
   ``unknown_or_foreign_child``.
4. **Agent-origin steering only**: ``steer`` stamps ``origin="agent"``, which
   :meth:`SubAgentManager.decide` refuses for inbox approvals — a plugin or parent agent
   can guide a running worker, never self-approve a human gate.
5. **Action Kernel & e-stop mediation**: spawns, steers, and stops cross the configured
   Action Kernel when enabled, and ``SubAgentManager`` enforces e-stop, kill-switch,
   pause, concurrency, recursion depth, and per-child wall-clock timeouts.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from .action_origin import current_action_origin
from .subagents import (
    DELEGATE_BLOCKED_CAPABILITIES,
    SubAgentManager,
    blocked_tool_names,
    child_tool_allowlist,
    current_spawn_id,
)


class SubagentLifecycleError(RuntimeError):
    """Structured error raised when a plugin violates a delegation boundary."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


class SubagentLifecycleAPI:
    """Stable governed lifecycle facade over :class:`SubAgentManager` for plugins (H650)."""

    def __init__(
        self,
        manager: SubAgentManager,
        *,
        parent_agent: str,
        parent_offer: Iterable[str],
        registered_tools: Iterable[str] | Callable[[], Iterable[str]] | None = None,
        session_id: str | Callable[[], str | None] | None = None,
        authorizer: Callable[..., Any] | None = None,
        plugin_id: str = "",
    ) -> None:
        if not isinstance(parent_agent, str) or not parent_agent.strip():
            raise ValueError("parent_agent must be a non-empty string")
        self._manager = manager
        self._parent_agent = parent_agent.strip()
        self._parent_offer = frozenset(str(t) for t in parent_offer if str(t).strip())
        self._registered_tools = registered_tools
        self._session_id = session_id
        self._authorizer = authorizer
        self._plugin_id = str(plugin_id or "").strip()[:64]

    @classmethod
    def for_orchestrator(
        cls,
        orch: Any,
        *,
        parent_agent: str = "jarvis",
        parent_offer: Iterable[str],
        session_id: str | Callable[[], str | None] | None = None,
        plugin_id: str = "",
    ) -> SubagentLifecycleAPI:
        """Build a lifecycle handle bound to a live ``Orchestrator`` instance."""
        manager = getattr(orch, "subagents", None)
        if manager is None:
            raise SubagentLifecycleError("subagents_unavailable", "orchestrator has no SubAgentManager")
        server = getattr(orch, "tool_rpc", None)

        def _registered() -> list[str]:
            if server is None:
                return list(parent_offer)
            return [str(t.get("name") or "") for t in server.tools(live=False)]

        def _resolved_session() -> str | None:
            if callable(session_id):
                return session_id()
            if isinstance(session_id, str):
                return session_id
            from .kernel.plan_mode import current_session

            return current_session()

        authorizer = getattr(orch, "action_kernel", None)
        return cls(
            manager,
            parent_agent=parent_agent,
            parent_offer=parent_offer,
            registered_tools=_registered,
            session_id=_resolved_session,
            authorizer=authorizer if callable(authorizer) else None,
            plugin_id=plugin_id,
        )

    @property
    def parent_agent(self) -> str:
        return self._parent_agent

    @property
    def parent_offer(self) -> frozenset[str]:
        return self._parent_offer

    def _active_session_id(self) -> str | None:
        if callable(self._session_id):
            return self._session_id()
        if isinstance(self._session_id, str):
            return self._session_id
        from .kernel.plan_mode import current_session

        return current_session()

    def _registered(self) -> frozenset[str]:
        if self._registered_tools is None:
            return self._parent_offer
        items = self._registered_tools() if callable(self._registered_tools) else self._registered_tools
        return frozenset(str(t) for t in items if str(t).strip())

    def resolve_child_tools(self, requested_tools: Iterable[str] | None = None) -> frozenset[str]:
        """Compute the child's allowed tools; raise if *requested_tools* escalates privilege."""
        registered = self._registered()
        max_allowed = child_tool_allowlist(
            registered, self._parent_offer, self._manager.blocked
        )
        if requested_tools is None:
            return max_allowed
        requested = frozenset(str(t) for t in requested_tools if str(t).strip())
        outside_parent = requested - self._parent_offer
        if outside_parent:
            raise SubagentLifecycleError(
                "privilege_escalation_refused",
                f"requested tools outside parent offer: {sorted(outside_parent)}",
            )
        blocked = requested & blocked_tool_names(
            DELEGATE_BLOCKED_CAPABILITIES | set(self._manager.blocked),
            registered | requested,
        )
        if blocked:
            raise SubagentLifecycleError(
                "privilege_escalation_refused",
                f"requested tools are blocked for sub-agents: {sorted(blocked)}",
            )
        return max_allowed & requested

    def _check_not_in_child(self) -> None:
        if current_spawn_id() is not None:
            raise SubagentLifecycleError(
                "delegation_blocked_for_subagents",
                "a running sub-agent cannot spawn or supervise further sub-agents",
            )

    def _check_kernel(self, op: str, count: int = 1) -> None:
        if self._authorizer is None:
            return
        from .kernel import Action, Verdict, kernel_enabled

        if not kernel_enabled():
            return
        decision = self._authorizer(
            Action(
                kind="tool.rpc",
                agent=self._parent_agent,
                title=f"Plugin sub-agent {op} ({count})",
                payload={
                    "tool": "subagent_lifecycle_api",
                    "target": op,
                    "count": count,
                    **({"plugin": self._plugin_id} if self._plugin_id else {}),
                },
                origin=current_action_origin(),
            )
        )
        verdict = getattr(decision, "verdict", None)
        if verdict is not Verdict.GRANT:
            reason = str(getattr(decision, "reason", "") or getattr(verdict, "value", "denied"))
            raise SubagentLifecycleError("kernel_denied", reason[:200])

    def _owns(self, rec: Mapping[str, Any] | None) -> bool:
        if not isinstance(rec, Mapping):
            return False
        return (
            rec.get("parent") == self._parent_agent
            and rec.get("parent_session") == self._active_session_id()
        )

    def _session_scope(self):
        from .llm.request_context import session_scope

        sid = self._active_session_id()
        return session_scope(sid)

    async def spawn(
        self,
        goal: str,
        *,
        context: str | None = None,
        output_schema: dict[str, Any] | None = None,
        tools: Iterable[str] | None = None,
        background: bool = False,
        read_only: bool = False,
        confine: str | None = None,
    ) -> dict[str, Any]:
        """Spawn a single isolated child under the parent's principal and narrowed tools."""
        self._check_not_in_child()
        allowed_offer = self.resolve_child_tools(tools)
        self._check_kernel("spawn", 1)
        with self._session_scope():
            if background:
                return await self._manager.spawn_background(
                    goal,
                    agent=self._parent_agent,
                    parent=self._parent_agent,
                    tools=allowed_offer,
                    context=context,
                    answer_schema=output_schema,
                    focused=True,
                    read_only=read_only,
                    confine=confine,
                )
            return await self._manager.spawn(
                goal,
                agent=self._parent_agent,
                parent=self._parent_agent,
                tools=allowed_offer,
                context=context,
                answer_schema=output_schema,
                focused=True,
                read_only=read_only,
                background=False,
                confine=confine,
            )

    async def spawn_batch(
        self,
        tasks: Sequence[Mapping[str, Any]],
        *,
        tools: Iterable[str] | None = None,
        background: bool = False,
    ) -> dict[str, Any]:
        """Spawn a batch of independent sub-agent tasks in parallel up to free slots."""
        self._check_not_in_child()
        if not tasks:
            raise SubagentLifecycleError("tasks_required", "at least one task is required")
        allowed_offer = self.resolve_child_tools(tools)
        self._check_kernel("spawn_batch", len(tasks))
        batch = []
        for item in tasks:
            goal = str(item.get("goal") or item.get("task") or "").strip()
            if not goal:
                raise SubagentLifecycleError("invalid_goal", "every batch task needs a non-empty goal")
            entry: dict[str, Any] = {"task": goal, "agent": self._parent_agent}
            if item.get("context"):
                entry["context"] = str(item["context"])
            schema = item.get("output_schema") or item.get("answer_schema")
            if schema is not None:
                entry["answer_schema"] = schema
            batch.append(entry)
        with self._session_scope():
            return await self._manager.spawn_batch(
                batch,
                parent=self._parent_agent,
                tools=allowed_offer,
                model_authored=True,
                queue=False,
                background=background,
            )

    def list(self, *, status: str | None = None) -> list[dict[str, Any]]:
        """List sub-agents belonging to this caller's parent agent and session."""
        self._check_not_in_child()
        rows = [row for row in self._manager.list() if self._owns(row)]
        if status is not None:
            rows = [row for row in rows if row.get("status") == status]
        return rows

    def get(self, spawn_id: str) -> dict[str, Any]:
        """Inspect one owned sub-agent record (raises on unknown or foreign spawn_id)."""
        self._check_not_in_child()
        rec = self._manager.get(spawn_id)
        if not self._owns(rec):
            raise SubagentLifecycleError(
                "unknown_or_foreign_child",
                f"{spawn_id!r} does not belong to ({self._parent_agent}, {self._active_session_id()})",
            )
        return rec  # type: ignore[return-value]

    def steer(self, spawn_id: str, message: str) -> dict[str, Any]:
        """Deliver an agent-origin guidance message to a running owned child."""
        self._check_not_in_child()
        self._check_kernel("steer", 1)
        rec = self._manager.get(spawn_id)
        if not self._owns(rec):
            raise SubagentLifecycleError(
                "unknown_or_foreign_child",
                f"{spawn_id!r} does not belong to ({self._parent_agent}, {self._active_session_id()})",
            )
        return self._manager.steer(spawn_id, message, origin="agent")

    def stop(self, spawn_id: str, *, reason: str = "plugin_stop") -> dict[str, Any]:
        """Cancel a running owned child."""
        self._check_not_in_child()
        self._check_kernel("stop", 1)
        rec = self._manager.get(spawn_id)
        if not self._owns(rec):
            raise SubagentLifecycleError(
                "unknown_or_foreign_child",
                f"{spawn_id!r} does not belong to ({self._parent_agent}, {self._active_session_id()})",
            )
        tag = f"plugin:{self._plugin_id}:{reason}" if self._plugin_id else f"plugin:{reason}"
        return self._manager.stop(spawn_id, reason=tag[:80])

    async def collect(self) -> list[dict[str, Any]]:
        """Claim finished background completions for this conversation once."""
        self._check_not_in_child()
        consumer = f"plugin:{self._plugin_id or self._parent_agent}"[:80]
        return await self._manager.claim_completions(
            consumer, parent_session=self._active_session_id()
        )

    def stats(self) -> dict[str, Any]:
        """Return live concurrency cap, active/free slots, timeout and blocked capabilities."""
        raw = self._manager.stats()
        cap = int(raw.get("cap") or 1)
        active = int(raw.get("active") or 0)
        return {
            "cap": cap,
            "active": active,
            "free_slots": max(0, cap - active),
            "max_depth": raw.get("max_depth", 1),
            "timeout_seconds": raw.get("timeout_seconds"),
            "blocked_capabilities": sorted(raw.get("blocked") or DELEGATE_BLOCKED_CAPABILITIES),
            "steerable": bool(raw.get("steerable")),
        }


__all__ = ["SubagentLifecycleAPI", "SubagentLifecycleError"]
