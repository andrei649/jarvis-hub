"""K1: the model may write one script that orchestrates many tool calls.

K0 (``sandbox_invocation.py``) answered *on whose authority* a call from inside the
sandbox is made. This is the door K0 was built in front of: ``execute_code`` puts the
existing governed pipeline on the tool surface, so the model can filter, branch and
loop over tool results **inside** the sandbox instead of paying context for every
intermediate byte. Nothing about the transport is new — ``ToolRPCSandboxRuntime``,
the file-RPC shim and the allowlist are unchanged. What is new is that a model turn
can reach them, and the conditions under which it may.

Four properties make offering it safe, and each is a refusal a test pins:

* **It calls K0; it derives nothing.** The offered set, the identity and the lifetime
  all come from ``sandbox_invocation.bind`` over the live registry and the turn's own
  principal. There is no argument for any of them, so a script cannot ask to be
  someone else or to reach a tool the turn was not shown.
* **It cannot call itself.** ``execute_code`` is removed from the registry rows handed
  to ``bind``, so a script that calls it gets ``tool_not_offered`` — one script, one
  container, one budget, no recursive fan-out.
* **It never runs outside isolation.** Without a Docker/WASM backend the call is
  refused rather than falling back to the host interpreter. The subprocess fallback
  is for a developer at a terminal, never for model-written code. The delivery plan
  asked for the tool to be *offered* only when a backend is usable; it is offered on
  the owner's switch and refuses at call time instead, because a per-turn
  availability probe is a mechanism this codebase does not have — that is H295's
  own open gap, and registering on a boot-time probe would make the offered set
  depend on whether a daemon happened to be up when the hub started.
* **It is off until the owner turns it on.** ``llm.execute_code`` defaults to False and
  the tool is not registered at all while it is off — an unusable tool on the surface
  costs the model context and teaches it to try something that always refuses.

Ungated, and that is a claim about the container rather than about the code: inside the
sandbox a gated tool cannot execute at all — ``ToolRPCServer.handle`` answers
``approval_required`` and enqueues the owner's card — the network is ``--network none``,
the filesystem is read-only, and every response is secret-scrubbed on the way back.
``untrusted_output=True`` because stdout is whatever third-party content the script
chose to print, so the tool loop fences it as DATA and raises the turn's taint.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence

from .action_origin import current_action_origin
from .environments.output_limits import TruncatedText, truncate_text
from .sandbox_invocation import bind
from .tool_rpc import ToolRPCValidationError, current_tool_actor

logger = logging.getLogger("jarvis.code_tools")

TOOL = "execute_code"
SETTING = "llm.execute_code"
SESSION_SETTING = "llm.execute_code_sessions"
MAX_TOOL_CALLS_SETTING = "security.sandbox_max_tool_calls"

MAX_CODE_CHARS = 32_768
#: Hermes's own stdout budget, and a *ceiling* rather than a second truncation: the
#: sandbox already bounds each stream at ``max_output_bytes`` while it reads the child,
#: with an honest inline notice. So this pass runs only on a host configured to allow
#: more than this, and is skipped when the sandbox's own cap is already the tighter of
#: the two — one truncation, one notice, never two nested ones. Spilling the remainder
#: to a file instead of dropping it is a separate row and is not implemented here.
MAX_OUTPUT_BYTES = 50_000
DEFAULT_MAX_TOOL_CALLS = 50

CODE_REQUIRED = "code_required"
CODE_TOO_LONG = "code_too_long"
INVALID_ARGS = "invalid_args"
SESSION_DENIED = "cell_denied"
DISABLED = "code_execution_disabled"
SANDBOX_UNAVAILABLE = "sandbox_unavailable"
NOT_ISOLATED = "sandbox_not_isolated"
AUTHORITY_UNAVAILABLE = "authority_unavailable"

INPUT_SCHEMA = {
    "type": "object",
    "required": ["code"],
    "additionalProperties": False,
    "properties": {
        "code": {"type": "string", "minLength": 1, "maxLength": MAX_CODE_CHARS},
        # K2 only, and advertised only when session kernels are on: start this cell
        # in a fresh interpreter. Losing state has to be something a caller can ask
        # for on purpose, or the only way out of a wedged namespace is a new session.
        "reset": {"type": "boolean"},
    },
}

SESSION_SCHEMA = INPUT_SCHEMA
ONESHOT_SCHEMA = {
    "type": "object", "required": ["code"], "additionalProperties": False,
    "properties": {"code": INPUT_SCHEMA["properties"]["code"]},
}

DESCRIPTION = (
    "Run one Python script in the isolated sandbox. Inside it, "
    "jarvis_tool_call(name, args) reaches the same tools this turn was offered, so "
    "many calls can be filtered and combined without returning here between them."
)
SESSION_DESCRIPTION = DESCRIPTION + (
    " Variables, imports and loaded data persist between calls in this session; the "
    "result says whether it continued or started over. Pass reset=true for a fresh "
    "interpreter."
)


def _output_ceiling(sandbox) -> tuple[int, bool]:
    """The byte ceiling on each stream, and whether *this* layer is the one enforcing it.

    The sandbox bounds its child's streams as it reads them, so the effective limit is
    the smaller of the two. When that is the sandbox's own cap this layer must not run:
    the text it would re-truncate already ends in the sandbox's omission notice, and a
    notice nested inside a notice is worse than either.
    """
    try:
        sandbox_limit = int(getattr(sandbox, "max_output_bytes", MAX_OUTPUT_BYTES))
    except (TypeError, ValueError):
        sandbox_limit = MAX_OUTPUT_BYTES
    limit = max(8, min(MAX_OUTPUT_BYTES, sandbox_limit))
    return limit, limit < sandbox_limit


def _cap(text: str, limit: int, label: str, binding: bool) -> TruncatedText:
    """Apply this layer's ceiling, or hand the sandbox's own capped text straight back."""
    body = str(text or "")
    if not binding:
        return TruncatedText(text=body, truncated=False,
                             original_bytes=len(body.encode("utf-8")), omitted_bytes=0)
    return truncate_text(body, max_content_bytes=limit, label=label)


def _int_setting(settings: Callable[[str, object], object], key: str, default: int) -> int:
    try:
        return int(settings(key, default))
    except (TypeError, ValueError):
        return default


class CodeExecutionTool:
    """The handler, as an object so the wiring stays readable and testable."""

    def __init__(
        self,
        server,
        *,
        sandbox: Callable[[], object],
        settings: Callable[[str, object], object],
        agent_patterns: Callable[[str], Sequence[str] | None] | None = None,
        principal: Callable[[], object] | None = None,
        session_id: Callable[[], str] | None = None,
        kernels=None,
        authorizer: Callable[..., object] | None = None,
    ) -> None:
        self._server = server
        self._sandbox = sandbox
        self._settings = settings
        self._agent_patterns = agent_patterns
        self._principal = principal
        self._session_id = session_id
        # K2. Absent, or switched off, and every call is the K1 one-shot path.
        self._kernels = kernels
        self._authorizer = authorizer

    # ── authority ────────────────────────────────────────────────────────────

    def _offerable(self) -> list[Mapping[str, object]]:
        """The live registry minus this tool: one script never starts another."""
        return [row for row in self._server.tools() if row.get("name") != TOOL]

    def _invocation(self):
        """Bind this run's authority with K0, from host state only.

        The agent is the actor ``ToolRPCServer.handle`` is already running as, not a
        name from the arguments, and the principal and origin are the turn's own
        ContextVars — the same inputs the tool profile used to decide that this turn
        could see ``execute_code`` in the first place. Re-resolving them here is what
        keeps the inner reach equal to the outer offer instead of merely similar.
        """
        agent = current_tool_actor() or getattr(self._server, "agent", "jarvis")
        patterns = None
        if self._agent_patterns is not None:
            try:
                patterns = self._agent_patterns(agent)
            except Exception:
                logger.warning("agent tool patterns unreadable; binding without them",
                               exc_info=True)
                patterns = ()
        principal = None
        if self._principal is not None:
            try:
                principal = self._principal()
            except Exception:
                # Nobody in particular is the guest posture, never the owner's.
                principal = None
        session = ""
        if self._session_id is not None:
            try:
                session = str(self._session_id() or "")
            except Exception:
                session = ""
        invocation, _decision = bind(
            tools=self._offerable(),
            agent=agent,
            principal=principal,
            origin=current_action_origin(),
            session_id=session,
            settings=self._settings,
            agent_patterns=patterns,
        )
        return invocation

    # ── the arguments ────────────────────────────────────────────────────────

    def sessions_on(self) -> bool:
        """K2 is a second switch, not a consequence of the first."""
        if self._kernels is None:
            return False
        try:
            return self._settings(SESSION_SETTING, False) is True
        except Exception:
            logger.warning("session-kernel setting unreadable; leaving it off",
                           exc_info=True)
            return False

    def preflight(self, args: Mapping[str, object]) -> dict:
        """Enforce the advertised schema; the server only advertises it.

        ``input_schema`` is what the model is shown, not a validator — every other
        bounded tool here pairs it with a preflight, and a length cap the server does
        not enforce is decoration. Refusing an unknown key matters more than the cap:
        this tool's whole contract is that the only thing a caller supplies is code.
        """
        allowed = {"code", "reset"} if self.sessions_on() else {"code"}
        if set(args) - allowed:
            raise ToolRPCValidationError(INVALID_ARGS)
        code = args.get("code")
        if not isinstance(code, str) or not code.strip():
            raise ToolRPCValidationError(CODE_REQUIRED)
        if len(code) > MAX_CODE_CHARS:
            raise ToolRPCValidationError(CODE_TOO_LONG)
        reset = args.get("reset", False)
        if not isinstance(reset, bool):
            raise ToolRPCValidationError(INVALID_ARGS)
        return {"code": code, **({"reset": True} if reset else {})}

    # ── the call ─────────────────────────────────────────────────────────────

    async def execute(self, args: Mapping[str, object]) -> dict:
        from .tool_rpc_runtime import ToolRPCSandboxRuntime

        if self._settings(SETTING, False) is not True:
            return {"ok": False, "reason": DISABLED}
        sandbox = None
        try:
            sandbox = self._sandbox()
        except Exception:
            logger.warning("sandbox unavailable for execute_code", exc_info=True)
        if sandbox is None:
            return {"ok": False, "reason": SANDBOX_UNAVAILABLE}
        # Isolation is re-read per call, not at registration: a host whose Docker
        # daemon stopped since boot refuses the call rather than quietly running
        # model-written code on the host interpreter.
        try:
            isolated = bool(sandbox.is_isolated())
        except Exception:
            isolated = False
        if not isolated:
            return {"ok": False, "reason": NOT_ISOLATED}
        try:
            invocation = self._invocation()
        except Exception:
            # A run with no authority would still execute plain Python and refuse
            # every tool call. That is a confusing half-success for the model, so
            # the whole call is refused instead.
            logger.warning("execute_code authority binding failed", exc_info=True)
            return {"ok": False, "reason": AUTHORITY_UNAVAILABLE}

        code = str(args.get("code") or "")
        max_calls = max(0, _int_setting(
            self._settings, MAX_TOOL_CALLS_SETTING, DEFAULT_MAX_TOOL_CALLS))
        if self.sessions_on():
            return await self._session_cell(
                invocation, code, reset=bool(args.get("reset")), sandbox=sandbox)
        run = await ToolRPCSandboxRuntime(
            self._server, sandbox, invocation=invocation, max_tool_calls=max_calls,
        ).run_python(code)
        limit, binding = _output_ceiling(sandbox)
        stdout = _cap(run.result.stdout, limit, "STDOUT", binding)
        stderr = _cap(run.result.stderr, limit, "STDERR", binding)
        return {
            "ok": bool(run.result.success) and not run.timed_out,
            "stdout": stdout.text,
            "stderr": stderr.text,
            # True only when *this* pass cut something. When the sandbox's own cap was
            # the tighter one it truncated first, and says so inline in the stream.
            "truncated": stdout.truncated or stderr.truncated,
            "output_limit": limit,
            "exit_code": run.result.exit_code,
            "duration": run.result.duration,
            "tool_calls": run.tool_calls,
            "max_tool_calls": max_calls,
            "timed_out": run.timed_out,
            "offered_tools": sorted(invocation.offered),
        }


    # ── K2: the session path ─────────────────────────────────────────────────

    async def _session_cell(self, invocation, code: str, *, reset: bool, sandbox) -> dict:
        """Run one cell in this session's kernel, re-earning the right to first.

        The invocation is this cell's own — bound moments ago from the live principal
        — and the broker is built from it, so the interpreter's age buys the cell
        nothing. ``authorize`` crosses the Action Kernel before a byte is written; a
        DENY (a halted kill-switch, an over-budget agent, a runaway loop) stops the
        cell here rather than at whatever it would have done next.
        """
        from .tool_rpc_runtime import ToolCallBroker

        if reset:
            await self._kernels.reset(invocation)
        outcome = await self._kernels.run(
            invocation, code,
            authorize=lambda cell: self._authorize_cell(invocation),
            broker=ToolCallBroker(self._server, invocation),
        )
        limit, binding = _output_ceiling(sandbox)
        stdout = _cap(outcome.stdout, limit, "STDOUT", binding)
        stderr = _cap(outcome.stderr, limit, "STDERR", binding)
        return {
            **outcome.as_dict(),
            "stdout": stdout.text,
            "stderr": stderr.text,
            "truncated": stdout.truncated or stderr.truncated,
            "output_limit": limit,
            "session": True,
            "offered_tools": sorted(invocation.offered),
        }

    def _authorize_cell(self, invocation) -> None:
        """Cross the Action Kernel for this cell, or refuse it.

        A resident interpreter authorized once and then fed arbitrary later code is a
        kernel bypass with extra steps. No new action kind: a cell is a ``tool.rpc``
        effect, the same boundary the one-shot path already sits behind.
        """
        if self._authorizer is None:
            return
        from .kernel import Action, Verdict

        try:
            decision = self._authorizer(Action(
                kind="tool.rpc", agent=invocation.agent,
                title="Run one code cell in the session kernel",
                payload={"tool": TOOL, "target": TOOL, "session": invocation.session_id},
                origin=invocation.origin,
            ))
        except Exception:
            logger.warning("session cell authorization failed", exc_info=True)
            raise ToolRPCValidationError(SESSION_DENIED) from None
        if getattr(decision, "verdict", None) is Verdict.DENY:
            raise ToolRPCValidationError(SESSION_DENIED)


def register_code_tools(
    server,
    *,
    sandbox: Callable[[], object],
    settings: Callable[[str, object], object],
    agent_patterns: Callable[[str], Sequence[str] | None] | None = None,
    principal: Callable[[], object] | None = None,
    session_id: Callable[[], str] | None = None,
    kernels=None,
    authorizer: Callable[..., object] | None = None,
) -> list[str]:
    """Register ``execute_code`` when the owner has switched it on, else nothing.

    Returning ``[]`` and touching no registry is the default: the tool profile can
    only narrow what exists, so "off" has to mean "never registered", not "registered
    and refused".
    """
    try:
        enabled = settings(SETTING, False) is True
    except Exception:
        logger.warning("execute_code setting unreadable; leaving it off", exc_info=True)
        enabled = False
    if not enabled:
        return []
    tool = CodeExecutionTool(
        server, sandbox=sandbox, settings=settings, agent_patterns=agent_patterns,
        principal=principal, session_id=session_id, kernels=kernels,
        authorizer=authorizer,
    )
    sessions = tool.sessions_on()
    server.register_tool(
        TOOL,
        tool.execute,
        # The model is shown what it can actually do: `reset` and the persistence
        # promise appear only where a kernel is really behind the tool.
        description=SESSION_DESCRIPTION if sessions else DESCRIPTION,
        input_schema=SESSION_SCHEMA if sessions else ONESHOT_SCHEMA,
        capability_id="tool:execute_code",
        preflight=tool.preflight,
        # Stdout is whatever the script printed, which is where a fetched page or a
        # search hit ends up. The fence follows the tool, so it is declared once here.
        untrusted_output=True,
    )
    return [TOOL]


__all__ = [
    "AUTHORITY_UNAVAILABLE", "CODE_REQUIRED", "CODE_TOO_LONG", "CodeExecutionTool",
    "DISABLED", "INPUT_SCHEMA", "INVALID_ARGS",
    "MAX_CODE_CHARS", "MAX_OUTPUT_BYTES", "NOT_ISOLATED", "SANDBOX_UNAVAILABLE",
    "SETTING", "TOOL", "register_code_tools",
]
