"""
tool_rpc.py — H20.1 Governed Tool-RPC (`execute_code`).

The agent writes a Python script that orchestrates many Jarvis tool calls and
runs it in the sandbox; inside, the script reaches the tools through a local RPC
surface instead of round-tripping every step through the LLM context →
"zero-context-cost pipelines" (the biggest net capability from hermes-agent).

This module is the **governed RPC surface** — the security-critical core:

  * **Allowlist:** only explicitly registered tools are callable; anything else
    is denied (the sandbox can't reach arbitrary host functions).
  * **Risk gating:** read-only tools run inline; *gated* (external/mutating)
    tools never execute from the sandbox — they enqueue an ask-tier governed
    task and return ``approval_required`` (the script can't escalate).
  * **Call classes (H506):** a gated tool may register a *classifier* saying that
    some of its calls are a distinct class the owner must be told about — a
    ``file_write`` to ``SOUL.md`` is not the ask a ``file_write`` to a scratch note
    is. The class is stamped on the approval card (payload and title), and
    ``execute`` re-derives it and refuses (``approval_class_mismatch``) unless the
    approved card carried it: a classed call runs only off an approval that named
    the class. The classifier is registrar-owned, so call data can neither label
    its own call nor strip the label off.
  * **Secret containment:** the sandbox never sees secrets — handlers resolve
    credentials host-side, and every response is run through the secret-scrubber
    (defense-in-depth) before it crosses back.

The Unix-socket transport + the sandbox-side client + actually running the
agent's code in the sandbox are the host seam; the governance core here is pure
and offline-testable. The injected sink/secret-broker keep it decoupled.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from contextvars import ContextVar
from copy import deepcopy
from typing import Awaitable, Callable, Optional

from .automation_contracts import ContractTemplate, predicate
from .security.quarantine import strip_invisible_deep
from .turn_approvals import record_pending_approval

logger = logging.getLogger("jarvis.tool_rpc")
#: Tools whose override failed, so the WARNING is logged once per failing tool, not
#: on every tool-list build; a hook that recovers is cleared and warns again if it fails.
_OVERRIDE_WARNED: set[str] = set()

#: Who the call in flight is being made *as*. ``handle`` resolves the actor once and
#: publishes it here for the length of the handler, so a handler that has to make an
#: authority decision of its own (``execute_code`` binds a sandbox invocation) reads the
#: identity the server settled on instead of guessing the server's default agent. It is
#: written by ``handle`` only, and reset in a ``finally``: nothing leaks to the next call.
_tool_actor: ContextVar[str] = ContextVar("jarvis_tool_actor", default="")


def current_tool_actor() -> str:
    """The actor of the ToolRPC call in flight, or ``""`` outside one."""
    return _tool_actor.get()


#: Which model turn a call belongs to (H315 second review): the tool loop binds a fresh
#: token for each run and a script's calls run with none, so a tool can tell text the
#: model itself sent in this turn (it is in the transcript already) from text an earlier
#: turn or a script wrote. ``None`` outside a loop run.
_tool_turn: ContextVar[Optional[str]] = ContextVar("jarvis_tool_turn", default=None)


def bind_tool_turn(token: Optional[str]):
    """Bind the turn the next calls belong to; returns the reset token."""
    return _tool_turn.set(token)


def reset_tool_turn(token) -> None:
    _tool_turn.reset(token)


def current_tool_turn() -> Optional[str]:
    """The model turn of the call in flight, or ``None`` (no loop run, or a script)."""
    return _tool_turn.get()


Handler = Callable[[dict], Awaitable]
Preflight = Callable[[dict], Mapping]
GatedIntake = Callable[[str, dict], int]
#: H506 — a *registrar-supplied* look at one call's arguments that answers "is this
#: call a distinct class of thing the owner must be told about?". Returns a small
#: mapping of labels (``class``, ``notice``, plus flat scalars) or ``None``. It is
#: server-owned like :data:`Preflight`: call data selects the tool, never the
#: classifier, so a script cannot label its own call — or unlabel it.
Classifier = Callable[[dict], Optional[Mapping]]
#: H296 — a zero-argument hook that states what the live install can do, merged over a
#: tool's static schema every time the tool list is built (see ``advertised_schema``).
SchemaOverrides = Callable[[], Optional[Mapping]]
#: The longest description an override may advertise.
MAX_OVERRIDE_DESCRIPTION = 2048
_OVERRIDE_KEYS = frozenset({"description", "properties", "required"})


def _apply_override(description: str, schema: dict, patch: object) -> tuple[str, dict]:
    """Merge one hook answer over a static (description, schema); raise on anything else.

    An answer may carry ``description`` (text), ``properties`` (per-property keys
    merged over properties the static schema already declares: an override narrows
    an argument, it never invents one) and ``required`` (names the schema declares).
    ``None`` or ``{}`` means "nothing to change".
    """
    import json

    if patch is None:
        return description, schema
    if not isinstance(patch, Mapping):
        raise TypeError("an override must be a mapping")
    unknown = set(patch) - _OVERRIDE_KEYS
    if unknown:
        raise ValueError(f"unknown override keys: {sorted(unknown)}")
    if "description" in patch:
        text = patch["description"]
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_OVERRIDE_DESCRIPTION:
            raise ValueError("an override description must be non-empty text")
        description = text
    declared = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    props = patch.get("properties")
    if props is not None:
        if not isinstance(props, Mapping):
            raise TypeError("override properties must be a mapping")
        merged = dict(declared)
        for key, value in props.items():
            if key not in declared or not isinstance(value, Mapping) or not isinstance(declared[key], Mapping):
                raise ValueError(f"override for an undeclared or malformed property: {key!r}")
            merged[key] = {**declared[key], **deepcopy(dict(value))}
        schema = {**schema, "properties": merged}
    if "required" in patch:
        names = patch["required"]
        if not isinstance(names, list) or any(n not in declared for n in names):
            raise ValueError("override required must name declared properties")
        schema = {**schema, "required": list(names)}
    json.dumps(schema)            # plain JSON only: a set, a NaN or an object cannot reach a model
    return description, schema


def advertised_schema(name: str, description: str, schema: Mapping,
                      overrides: SchemaOverrides | None) -> tuple[str, dict]:
    """What a tool tells the model it accepts, now (H296): its static description and
    schema with the live override merged in, or the static ones when the hook raises
    or answers something malformed (logged once per tool until it recovers)."""
    static_description, static_schema = description, deepcopy(dict(schema))
    if overrides is None:
        return static_description, static_schema
    try:
        merged = _apply_override(static_description, static_schema, overrides())   # it never mutates
    except Exception as exc:  # noqa: BLE001 - a hook never breaks the tool list
        if name not in _OVERRIDE_WARNED:
            _OVERRIDE_WARNED.add(name)
            logger.warning("tool %s: its live schema could not be built (%s); advertising its "
                           "static schema", name, type(exc).__name__)
        return static_description, static_schema
    _OVERRIDE_WARNED.discard(name)
    return merged

#: Label keys a classifier may not set: they are the card's own identity.
_RESERVED_LABEL_KEYS = frozenset({"tool", "args", "target"})
_MAX_LABELS = 8
_MAX_LABEL_CHARS = 200

_KIND_PREFIX = "toolrpc."
_RISK_TIER = 2


def _tool_rpc_call_contract_template() -> ContractTemplate:
    """Contract form of the existing gated Tool-RPC approval path."""
    def tool_kind(view, now):
        tool = view.get("tool")
        kind = view.get("kind")
        return isinstance(tool, str) and bool(tool) and kind == f"{_KIND_PREFIX}{tool}"

    def gated_tool(view, now):
        return view.get("gated") is True

    def target_matches_tool(view, now):
        return view.get("target") == view.get("tool")

    def args_keys_are_safe(view, now):
        keys = view.get("args_keys")
        return (
            isinstance(keys, list)
            and all(isinstance(k, str) for k in keys)
            and keys == sorted(keys)
        )

    return ContractTemplate(kind="tool_rpc_call", constraints=(
        predicate("tool_kind", tool_kind, reason="invalid_kind"),
        predicate("gated_tool", gated_tool, reason="not_gated"),
        predicate("target_matches_tool", target_matches_tool,
                  reason="target_mismatch"),
        predicate("args_keys_are_safe", args_keys_are_safe,
                  reason="bad_args_keys"),
    ), description="Admissibility for governed gated Tool-RPC calls.")


TOOL_RPC_CALL_CONTRACT = _tool_rpc_call_contract_template()


class ToolRPCValidationError(ValueError):
    """Bounded public denial raised by a tool-specific argument preflight."""

    def __init__(self, reason: str = "validation_failed") -> None:
        normalized = str(reason or "validation_failed")
        if (
            len(normalized) > 80
            or not normalized.replace("_", "").isalnum()
        ):
            normalized = "validation_failed"
        self.reason = normalized
        super().__init__(normalized)


class ToolRPCServer:
    """Allowlisted, risk-gated, secret-scrubbed tool surface for sandboxed code."""

    def __init__(self, secret_broker=None, enqueue: Optional[Callable] = None,
                 audit=None, agent: str = "jarvis", kernel=None,
                 execution_context_check: Optional[Callable] = None) -> None:
        self._tools: dict[str, dict] = {}
        self._secrets = secret_broker
        self._enqueue = enqueue
        self._audit = audit
        self.agent = agent
        self._kernel = kernel   # ORIZONT-24 K1 wave-3: bound kernel.authorize (default-off)
        self._execution_context_check = execution_context_check

    # ── registration (the allowlist) ─────────────────────────────────────────

    def register_tool(
        self,
        name: str,
        handler: Handler,
        gated: bool = False,
        description: str = "",
        input_schema: Optional[dict] = None,
        capability_id: str | None = None,
        preflight: Preflight | None = None,
        trusted_execution: bool = False,
        untrusted_output: bool = False,
        gated_intake: GatedIntake | None = None,
        classifier: Classifier | None = None,
        max_result_bytes: int | None = None,
        schema_overrides: SchemaOverrides | None = None,
    ) -> "ToolRPCServer":
        """Expose one tool. ``gated=True`` ⇒ external/mutating ⇒ needs approval.

        ``untrusted_output=True`` declares that what the handler returns is content
        from outside the box (a web page, a search result, an OSINT lookup). The tool
        loop fences such a result as DATA before the model reads it and raises the
        turn's recall taint so an action built from it queues for approval
        (Hermes absorption 5a). The declaration is per tool, never per call.

        ``classifier`` (H506) lets the registrar say that *some* calls to this tool
        are a distinct class the owner must be told about — a ``file_write`` whose
        target steers a future run (``SOUL.md``, ``AGENTS.md``, ...) is not the same
        ask as a ``file_write`` to a scratch note. Its labels are stamped onto the
        approval card the owner reads, and :meth:`execute` re-derives them and
        refuses a call whose approved card did not carry the class it belongs to —
        so a classed call can only ever run off an approval that named the class.
        Gated tools only: an ungated tool never produces a card to label.

        ``max_result_bytes`` is this tool's own statement of how much it may put in
        the context window (H298). It is the fourth rung of the threshold ladder —
        below a pinned tool and the owner's override, above the global default — and
        is the rung only the registrar can fill: a tool that knows its output is
        always small says so here rather than waiting for someone to configure it.

        ``schema_overrides`` (H296) is a zero-argument hook that tells the model what
        this install can do right now: the targets actually registered, the actions
        this driver accepts, the rooms that have a speaker. It is called every time
        the tool list is built and merged over the static schema (see
        :func:`advertised_schema`); a hook that raises or answers something
        malformed is logged and the static schema is advertised instead. It narrows
        what is advertised; the handler's own checks still decide every call.
        """
        if max_result_bytes is not None:
            try:
                max_result_bytes = int(max_result_bytes)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("max_result_bytes must be a byte count") from exc
            if max_result_bytes <= 0:
                raise ValueError("max_result_bytes must be positive")
        if trusted_execution and not gated:
            raise ValueError("trusted execution is only valid for gated tools")
        if gated_intake is not None and (
            not callable(gated_intake) or not gated or not trusted_execution
        ):
            raise ValueError("custom intake requires a trusted gated tool")
        if classifier is not None and (not callable(classifier) or not gated):
            raise ValueError("a call classifier requires a gated tool")
        if schema_overrides is not None and not callable(schema_overrides):
            raise ValueError("schema_overrides must be a zero-argument callable")
        if capability_id is not None:
            if (
                not isinstance(capability_id, str)
                or not capability_id
                or len(capability_id) > 128
                or any(not (char.isalnum() or char in ":._-*") for char in capability_id)
            ):
                raise ValueError("capability_id must be a bounded machine identifier")
            if any(
                existing_name != name and spec.get("capability_id") == capability_id
                for existing_name, spec in self._tools.items()
            ):
                raise ValueError(f"capability_id already registered: {capability_id}")
        schema = input_schema if input_schema is not None else {
            "type": "object",
            "properties": {},
        }
        existing = self._tools.get(name)
        if existing is not None and existing.get("active_tasks"):
            raise RuntimeError(f"tool has in-flight calls: {name}")
        self._tools[name] = {
            "handler": handler,
            "gated": bool(gated),
            "description": description,
            "input_schema": deepcopy(schema),
            "capability_id": capability_id,
            "preflight": preflight,
            "trusted_execution": bool(trusted_execution),
            "untrusted_output": bool(untrusted_output),
            "gated_intake": gated_intake,
            "classifier": classifier,
            "max_result_bytes": max_result_bytes,
            "schema_overrides": schema_overrides,
            "active_tasks": set(),
        }
        return self

    async def unregister_tool(
        self,
        name: str,
        *,
        cancel_inflight: bool = False,
        timeout: float = 5.0,
    ) -> bool:
        """Deny new calls immediately, then drain or cancel calls already running."""
        spec = self._tools.pop(str(name or ""), None)
        if spec is None:
            return False
        current = asyncio.current_task()
        tasks = [task for task in tuple(spec.get("active_tasks", ())) if task is not current]
        if cancel_inflight:
            for task in tasks:
                task.cancel()
        if tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=max(0.01, min(30.0, float(timeout))),
                )
            except TimeoutError:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        return True

    def tools(self) -> "list[dict]":
        tools = []
        for name, spec in sorted(self._tools.items()):
            description, schema = advertised_schema(
                name, spec["description"], spec["input_schema"], spec.get("schema_overrides"))
            row = {
                "name": name,
                "gated": spec["gated"],
                "description": description,
                "input_schema": schema,
            }
            if spec.get("capability_id"):
                row["capability_id"] = spec["capability_id"]
            if spec.get("untrusted_output"):
                # Only when declared: rows of trusted tools stay byte-identical, so the
                # tool-profile snapshot and the pinned allowlists do not move.
                row["untrusted_output"] = True
            tools.append(row)
        return tools

    def declared_result_bytes(self, name: str) -> int | None:
        """What this tool said about its own output size, if it said anything.

        Deliberately not part of :meth:`tools`: that list is snapshotted and shipped
        to the model, and a budgeting detail is neither the model's business nor
        something that should move a pinned allowlist.
        """
        spec = self._tools.get(str(name or ""))
        return None if spec is None else spec.get("max_result_bytes")

    def declares_untrusted_output(self, name: str) -> bool:
        """Whether this tool said what it returns comes from outside the box."""
        spec = self._tools.get(str(name or ""))
        return bool(spec and spec.get("untrusted_output"))

    def allows(self, name: str) -> bool:
        return name in self._tools

    # ── the RPC entry point ──────────────────────────────────────────────────

    async def handle(self, request: dict, *, actor: Optional[str] = None) -> dict:
        effective_actor = actor or self.agent
        name = str((request or {}).get("tool", ""))
        args = (request or {}).get("args") or {}
        if not isinstance(args, dict):
            return {"ok": False, "reason": "bad_args", "tool": name}

        from .job_toolsets import allows
        if not allows(name):
            return {"ok": False, "reason": "job_toolset_not_allowed", "tool": name}

        spec = self._tools.get(name)
        if spec is None:
            # Not on the allowlist — the sandbox cannot reach it.
            return {"ok": False, "reason": "tool_not_allowed", "tool": name}

        args, denial = self._run_preflight(spec, args, name)
        if denial is not None:
            return denial

        if spec["gated"]:
            # External/mutating tool: never runs from the sandbox. Enqueue an
            # ask-tier governed task; the script gets back "approval_required".
            contract_payload = {
                "kind": f"{_KIND_PREFIX}{name}",
                "tool": name,
                "target": name,
                "agent": effective_actor,
                "risk_tier": _RISK_TIER,
                "gated": True,
                "args_keys": sorted(args.keys()),
            }
            try:
                decision = TOOL_RPC_CALL_CONTRACT.evaluate(
                    contract_payload, now=time.time())
            except Exception:
                logger.warning("tool-rpc contract evaluation failed", exc_info=True)
                return {"ok": False, "reason": "contract_error", "tool": name}
            if not decision.admissible:
                reason = decision.reason or "contract_denied"
                self._record(
                    "toolrpc.contract_denied",
                    f"{name}: {reason}",
                    agent=effective_actor,
                )
                return {"ok": False, "reason": reason, "tool": name}

            # A server-owned intake can bind one finalized action/task tuple
            # through the production mediation bridge. It owns BOTH the kernel
            # gate and governed enqueue; call data cannot select this callback.
            intake = spec.get("gated_intake")
            if intake is not None:
                try:
                    task_id = intake(effective_actor, args)
                except ToolRPCValidationError as exc:
                    return {"ok": False, "reason": exc.reason, "tool": name}
                except Exception:
                    logger.warning("tool-rpc bound intake failed", exc_info=True)
                    return {"ok": False, "reason": "enqueue_failed", "tool": name}
                self._record("toolrpc.gated", name, agent=effective_actor)
                # The caller of the *turn* only ever sees the loop's prose reply, so
                # the id is noted here too — where it is known — for the collector the
                # turn holds. Reporting only: the row stays proposed either way.
                record_pending_approval(task_id)
                return {"ok": False, "reason": "approval_required", "tool": name, "task_id": task_id}

            # ORIZONT-24 K1 wave-3: mediate the gated tool through the Action Kernel
            # first (default-off). A DENY (halted kill-switch / over-budget / runaway
            # loop) refuses it before it even reaches the approval queue.
            denied = self._kernel_denial(name, args, effective_actor)
            if denied is not None:
                self._record(
                    "toolrpc.kernel_denied",
                    f"{name}: {denied}",
                    agent=effective_actor,
                )
                return {"ok": False, "reason": "kernel_denied", "tool": name, "detail": denied}
            if self._enqueue is None:
                return {"ok": False, "reason": "approval_required", "tool": name}
            # H506 — the card the owner reads must say what class of thing this is.
            # A file_write to SOUL.md and one to notes.txt used to be byte-identical
            # asks; the classifier's labels ride on the payload and, when it names a
            # class, in the title, so the owner decides knowing.
            labels, denial = self._classify(spec, args)
            if denial is not None:
                self._record(
                    "toolrpc.classify_failed", f"{name}: {denial}", agent=effective_actor)
                return {"ok": False, "reason": denial, "tool": name}
            payload = {"tool": name, "args": args, "target": name}
            payload.update(labels)
            title = f"Tool '{name}' via RPC"
            notice = labels.get("notice")
            if isinstance(notice, str) and notice:
                title = f"{title} — {notice}"
            try:
                task_id = self._enqueue(
                    effective_actor, f"toolrpc.{name}", title,
                    payload=payload,
                    risk_tier=_RISK_TIER, autonomy_level="ask", origin="generated")
            except Exception:
                logger.warning("tool-rpc gated enqueue failed", exc_info=True)
                return {"ok": False, "reason": "enqueue_failed", "tool": name}
            self._record("toolrpc.gated", name, agent=effective_actor)
            record_pending_approval(task_id)
            return {"ok": False, "reason": "approval_required", "tool": name, "task_id": task_id}

        try:
            result = await self._invoke_handler(spec, args, effective_actor)
        except Exception:
            logger.warning("tool-rpc handler failed: %s", name, exc_info=True)
            return {"ok": False, "reason": "tool_error", "tool": name}

        self._record("toolrpc.call", name, agent=effective_actor)
        # Invisible Unicode TAG characters never cross to the model or the sandbox: a
        # tool result (an MCP bridge, a fetched page, a file) can carry instructions the
        # owner cannot see on screen (Hermes absorption 4a).
        return {"ok": True, "tool": name, "result": self._scrub(strip_invisible_deep(result))}

    async def run_pipeline(self, requests: "list[dict]") -> "list[dict]":
        """Run a sequence of tool calls (what a sandboxed script does), returning
        each response. No LLM round-trip happens between steps."""
        return [await self.handle(r) for r in (requests or [])]

    async def execute(self, task, *, execution_context=None) -> dict:
        """Executor handler: run a gated tool AFTER its approval task is approved."""
        effective_actor = getattr(task, "agent", None) or self.agent
        payload = getattr(task, "payload", None)
        if not isinstance(payload, Mapping):
            return {"status": "failed", "reason": "bad_args", "tool": ""}
        name = payload.get("tool")
        if not isinstance(name, str):
            return {"status": "failed", "reason": "bad_args", "tool": ""}
        raw_args = payload.get("args", {})
        if not isinstance(raw_args, Mapping):
            return {"status": "failed", "reason": "bad_args", "tool": name}
        args = dict(raw_args)
        spec = self._tools.get(name)
        if spec is None:
            return {"status": "failed", "reason": "tool_not_allowed", "tool": name}
        args, denial = self._run_preflight(spec, args, name)
        if denial is not None:
            return {
                "status": "failed",
                "reason": denial["reason"],
                "tool": name,
            }
        # H506 — bind the approval to the class. The labels are re-derived here from
        # the args that are actually about to run, and must match the class the card
        # carried: a call that belongs to a class executes only off an approval that
        # named that class. This is not bypassable by the handler — the handler is
        # never reached — and it holds with the kernel off, which is the default.
        labels, classify_denial = self._classify(spec, args)
        if classify_denial is not None:
            self._record(
                "toolrpc.classify_failed", f"{name}: {classify_denial}",
                agent=effective_actor)
            return {"status": "failed", "reason": classify_denial, "tool": name}
        if labels.get("class") != payload.get("class"):
            self._record(
                "toolrpc.approval_class_mismatch",
                f"{name}: {payload.get('class')!r} approved, {labels.get('class')!r} now",
                agent=effective_actor)
            return {
                "status": "failed",
                "reason": "approval_class_mismatch",
                "tool": name,
            }
        if spec.get("trusted_execution"):
            try:
                trusted = (
                    self._execution_context_check is not None
                    and self._execution_context_check(execution_context, task) is True
                )
            except Exception:
                trusted = False
            if not trusted:
                return {
                    "status": "failed",
                    "reason": "trusted_execution_required",
                    "tool": name,
                }
        if spec["gated"]:
            denied = self._kernel_denial(name, args, effective_actor)
            if denied is not None:
                self._record(
                    "toolrpc.kernel_denied",
                    f"{name}: {denied}",
                    agent=effective_actor,
                )
                return {
                    "status": "failed",
                    "reason": "kernel_denied",
                    "tool": name,
                    "detail": denied,
                }
        try:
            result = await self._invoke_handler(spec, args, effective_actor)
        except Exception:
            logger.warning("tool-rpc approved execute failed: %s", name, exc_info=True)
            return {"status": "failed", "reason": "tool_error", "tool": name}
        if spec.get("trusted_execution") and not isinstance(result, Mapping):
            return {
                "status": "failed",
                "reason": "invalid_result",
                "tool": name,
            }
        if spec.get("trusted_execution") and result.get("ok") is not True:
            reason = result.get("reason")
            if not isinstance(reason, str) or not reason:
                reason = "invalid_result"
            return {
                "status": "failed",
                "reason": reason,
                "tool": name,
                "result": self._scrub(result),
            }
        self._record("toolrpc.execute", name, agent=effective_actor)
        return {"status": "ok", "tool": name, "result": self._scrub(result)}

    # ── internals ────────────────────────────────────────────────────────────

    @staticmethod
    async def _invoke_handler(spec: dict, args: dict, actor: str = ""):
        task = asyncio.current_task()
        active = spec["active_tasks"]
        if task is not None:
            active.add(task)
        token = _tool_actor.set(str(actor or ""))
        try:
            return await spec["handler"](args)
        finally:
            _tool_actor.reset(token)
            if task is not None:
                active.discard(task)

    def _classify(self, spec: dict, args: dict):
        """H506: the registrar's labels for this call, or a bounded denial.

        Returns ``(labels, None)`` or ``(None, reason)``. A classifier that blows up
        refuses the call rather than letting it through unlabelled: an unlabelled
        classed call is exactly the failure the class exists to prevent.
        """
        classifier = spec.get("classifier")
        if classifier is None:
            return {}, None
        try:
            raw = classifier(dict(args))
        except Exception:
            logger.warning("tool-rpc classifier failed", exc_info=True)
            return None, "classify_failed"
        if raw is None:
            return {}, None
        if not isinstance(raw, Mapping):
            return None, "classify_failed"
        labels: dict = {}
        for key, value in raw.items():
            if not isinstance(key, str) or key in _RESERVED_LABEL_KEYS:
                continue
            if isinstance(value, str):
                if len(value) > _MAX_LABEL_CHARS:
                    return None, "classify_failed"
            elif not isinstance(value, (bool, int, float)):
                continue
            labels[key] = value
            if len(labels) > _MAX_LABELS:
                return None, "classify_failed"
        cls = labels.get("class")
        if cls is not None and (
            not isinstance(cls, str) or not cls or len(cls) > 64
            or not cls.replace("_", "").replace(".", "").isalnum()
        ):
            return None, "classify_failed"
        return labels, None

    def _run_preflight(self, spec: dict, args: dict, name: str):
        preflight = spec.get("preflight")
        if preflight is None:
            return dict(args), None
        try:
            sanitized = preflight(dict(args))
        except ToolRPCValidationError as exc:
            return None, {"ok": False, "reason": exc.reason, "tool": name}
        except Exception:
            logger.warning("tool-rpc preflight failed: %s", name, exc_info=True)
            return None, {"ok": False, "reason": "validation_failed", "tool": name}
        if not isinstance(sanitized, Mapping):
            return None, {"ok": False, "reason": "validation_failed", "tool": name}
        return dict(sanitized), None

    def _scrub(self, obj):
        """Recursively mask any known secret value before it crosses to the sandbox."""
        if self._secrets is None:
            return obj
        if isinstance(obj, str):
            return self._secrets.redact(obj)
        if isinstance(obj, dict):
            return {self._scrub(k): self._scrub(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._scrub(v) for v in obj]
        if isinstance(obj, tuple):
            return tuple(self._scrub(v) for v in obj)
        if isinstance(obj, set):
            return {self._scrub(v) for v in obj}
        if isinstance(obj, frozenset):
            return frozenset(self._scrub(v) for v in obj)
        return obj

    def _kernel_denial(self, name: str, args: dict, actor: str) -> Optional[str]:
        """ORIZONT-24 K1 wave-3: ask the Action Kernel whether this gated tool may run.

        Returns a deny-reason string (block) or ``None`` (allow). Default-off: no kernel
        bound, or ``JARVIS_ACTION_KERNEL`` unset → ``None`` (unchanged behavior). Only the
        arg *keys* go in the payload, never values (which may carry secrets/PII).
        """
        if self._kernel is None:
            return None
        from agents.core.action_origin import current_action_origin
        from agents.core.kernel import Action, Verdict, kernel_enabled
        if not kernel_enabled():
            return None
        decision = self._kernel(Action(
            kind="tool.rpc", agent=actor,
            title=f"tool-rpc {name}",
            payload={"tool": name, "args_keys": sorted((args or {}).keys()), "target": name},
            origin=current_action_origin()))
        return decision.reason if decision.verdict is Verdict.DENY else None

    def _record(self, action: str, why: str, **meta) -> None:
        if self._audit is None:
            return
        try:
            if hasattr(self._audit, "record"):
                self._audit.record(actor="tool_rpc", action=action, why=why, metadata=meta)
            elif hasattr(self._audit, "log"):
                self._audit.log({"event": action, "why": why, **meta})
        except Exception:  # best-effort observability must not break the tool path
            logger.debug("tool-rpc audit sink failed", exc_info=True)
