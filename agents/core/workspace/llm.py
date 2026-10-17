"""The workspace's one door to a language model (spec §5 "llm.py", §8, Appendix A).

Why the hub's router and not the personal pipeline. The workspace answers company
employees, so it must never touch the owner's memory, agents or conversation state
(``orch.handle_input``). It asks the hub's ``HybridRouter`` for a backend directly,
under the organisation's ``model_policy``, and runs the call through the hub's own
guardrails and data-handling gate — the same governance every routed call gets.

The algorithm (Appendix A, followed step by step in :class:`HubEngine`):

1. the router comes from ``app_state.get_orch()`` — none yet → ``hub_not_ready``;
2. ``local_only`` takes ``router.local_backend`` (never ``select_backend``, which may
   spill to the cloud); ``allow_cloud`` lets the router choose;
3. ``check_data_handling`` must allow the route: an unattended call with no owner
   acknowledgment is refused, and under ``allow_cloud`` a cloud provider that may train
   on prompts is refused (a local route the gate allowed is allowed under both
   policies — ``allow_cloud`` widens what ``local_only`` permits, never narrows it);
4. locality is reported honestly: ``local`` only when the data policy says so;
5. the backend is bound to the hub's guardrails policy;
6. the stream runs inside the physical-request scope (every HTTP request the backend
   makes is re-checked) under a hard deadline;
7. backends never raise on failure — they answer fixed degraded strings — so those
   strings, and an empty answer, are turned into ``model_unavailable`` here;
8. model text is made valid Unicode (:func:`clean_text`) before any of it is streamed
   or returned: a lone surrogate could be neither stored nor sent as UTF-8.

Two layers. :func:`complete` and :func:`posture` are what callers use; they apply
the process-wide concurrency limit, the 64-character hold-back of streamed text (a
failure string is never shown to a user as if it were an answer) and the failure-reply
check to whichever engine is installed — the real :class:`HubEngine`, or a test
double installed with :func:`set_engine_for_tests`. Prompts and answers are never
logged.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import threading
import time
import weakref
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Protocol

from agents.core import app_state
from agents.core.llm.base import THINKING_EXHAUSTED_REPLY, is_backend_failure_reply
from agents.core.llm.data_handling import DataHandlingRefused, physical_request_scope
from agents.core.llm.hybrid_router import ModelNotApprovedError
from agents.core.security.guardrails import SecurityBlockError, bind_guardrails
from agents.core.web_helpers import BackendTimeout, bounded
from agents.core.workspace import config
from agents.core.workspace.errors import WorkspaceError

logger = logging.getLogger("nerva.workspace.llm")

#: The router agent id of every workspace call (POLICY_AUTO: local while the prompt fits).
AGENT_ID = "workspace"
LOCAL_ONLY = "local_only"
ALLOW_CLOUD = "allow_cloud"
#: Data policies under which ``allow_cloud`` may send company text to a provider.
CLOUD_SAFE_POLICIES = frozenset({"local", "no-training"})
#: Route names of local backends (Appendix A): test with startswith, never "cloud".
LOCAL_ROUTE_PREFIXES = ("local", "ollama")
#: Streamed text is held back until this many characters (or the end) are known.
HOLD_BACK_CHARS = 64
#: How long a call waits for a free model slot before answering ``model_busy``.
ACQUIRE_TIMEOUT_SECONDS = 30.0
BUSY_RETRY_AFTER_SECONDS = 10

TokenSink = Callable[[str], Awaitable[None] | None]

_SURROGATE = re.compile("[\ud800-\udfff]")
_HIGH_SURROGATES = ("\ud800", "\udbff")


def clean_text(text: str) -> str:
    """*text* as valid Unicode: no lone surrogates.

    A backend that decodes a stream chunk by chunk can split a UTF-16 surrogate pair
    (an emoji) across two chunks; joined again, the two halves are re-paired into the
    character they encode. Any surrogate still alone becomes ``?`` (UTF-8 ``replace``) —
    SQLite, JSON and the SSE stream all need text they can encode as UTF-8.
    """
    if not _SURROGATE.search(text):
        return text
    paired = text.encode("utf-16", "surrogatepass").decode("utf-16", "surrogatepass")
    return paired.encode("utf-8", "replace").decode("utf-8")


# ── results and errors ───────────────────────────────────────────────────────────────

@dataclass
class LLMResult:
    """One finished answer. ``locality`` is ``local``, ``cloud`` or ``unknown``."""

    text: str
    model: str
    route: str
    locality: str
    latency_ms: int


class LLMUnavailable(WorkspaceError):
    """No model could answer (``503 model_unavailable`` with a machine ``reason``).

    Reasons: ``hub_not_ready``, ``no_local_model``, ``no_model`` (``allow_cloud`` and
    nothing selectable), ``model_not_approved``, ``backend_error``, ``model_error`` (a
    backend's degraded reply), ``thinking_exhausted`` and ``empty_answer``.
    """

    def __init__(self, reason: str = "model_error", message: str = "", **extra: Any) -> None:
        super().__init__("model_unavailable", message or f"the model is not available ({reason})",
                         503, reason=reason, **extra)


class ModelPolicyBlocked(WorkspaceError):
    """The model policy forbids this route (``409 model_policy_blocked`` with ``reason``)."""

    def __init__(self, reason: str = "data_policy_unacknowledged", message: str = "",
                 **extra: Any) -> None:
        super().__init__("model_policy_blocked",
                         message or f"the model policy blocks this route ({reason})", 409,
                         reason=reason, **extra)


class ModelBusy(WorkspaceError):
    """Every model slot stayed taken for the whole acquire window (``503 model_busy``)."""

    def __init__(self, message: str = "") -> None:
        super().__init__("model_busy", message or "the model is busy; try again shortly", 503,
                         retry_after_seconds=BUSY_RETRY_AFTER_SECONDS)


class ModelTimeout(WorkspaceError):
    """The model did not finish in time (``504 model_timeout``)."""

    def __init__(self, seconds: float | None = None) -> None:
        detail = f" within {seconds:g} s" if seconds else " in time"
        super().__init__("model_timeout", f"the model did not answer{detail}", 504)


class ContentBlocked(WorkspaceError):
    """The hub's guardrails refused the prompt or the answer (``422 content_blocked``)."""

    def __init__(self) -> None:
        super().__init__("content_blocked", "the security policy blocked this content", 422)


# ── engines ──────────────────────────────────────────────────────────────────────────

class Engine(Protocol):
    """What :func:`complete` and :func:`posture` delegate to."""

    async def complete(self, *, system: str, prompt: str, policy: str, max_tokens: int,
                       temperature: float, on_token: Callable[[str], Awaitable[None]] | None,
                       timeout_seconds: float) -> LLMResult: ...

    async def posture(self, policy: str) -> dict: ...


def normalize_policy(policy: object) -> str:
    """``allow_cloud`` only when asked for exactly; anything else fails closed to local."""
    return ALLOW_CLOUD if policy == ALLOW_CLOUD else LOCAL_ONLY


def route_locality(data_policy: object, route: str) -> str:
    """Appendix A step 4: ``local`` only on the data policy's word."""
    if data_policy == "local":
        return "local"
    return "unknown" if route.startswith(LOCAL_ROUTE_PREFIXES) else "cloud"


def _hub() -> tuple[Any, Any]:
    orch = app_state.get_orch()
    router = getattr(orch, "llm_router", None) if orch is not None else None
    if router is None:
        raise LLMUnavailable("hub_not_ready", "the hub has not finished starting")
    return orch, router


def _select(router: Any, policy: str, prompt: str, *, preview: bool) -> tuple[Any, str, str]:
    """Appendix A step 2: ``(backend, model, route)`` for *policy*."""
    if policy == LOCAL_ONLY:
        try:
            backend = router.local_backend
        except RuntimeError as exc:
            raise LLMUnavailable("no_local_model", "no local model server is running") from exc
        return backend, router.get_model(AGENT_ID), "local"
    choose = router.preview_backend if preview else router.select_backend
    try:
        return choose(AGENT_ID, prompt)
    except ModelNotApprovedError as exc:
        raise LLMUnavailable("model_not_approved", "the routed model is not approved") from exc
    except RuntimeError as exc:
        raise LLMUnavailable("no_model", "no model route is available") from exc


def _authorize(router: Any, backend: Any, model: str, route: str, policy: str, *,
               actual_use: bool) -> dict:
    """Appendix A step 3: the data-handling verdict, or the refusal it implies.

    A provider the gate cannot identify (``ValueError``) is treated like an
    unacknowledged one: when the data handling is unknown, company text stays home.
    A gate that cannot decide at all (its consent store failed: another
    ``RuntimeError``) means no model may be used now — ``backend_error``.
    """
    try:
        handling = router.check_data_handling(backend, model, route, actual_use=actual_use)
    except (DataHandlingRefused, ValueError) as exc:
        raise ModelPolicyBlocked("data_policy_unacknowledged",
                                 "the hub owner has not acknowledged this model's data "
                                 "handling") from exc
    except RuntimeError as exc:
        logger.warning("workspace data-handling check failed: %s", type(exc).__name__)
        raise LLMUnavailable("backend_error", "the data-handling check failed") from exc
    # Only a cloud route can train on company text: a local route the gate allowed (a
    # LAN model server whose "unknown" handling the owner acknowledged) runs under
    # allow_cloud exactly as it does under local_only.
    if (policy == ALLOW_CLOUD and not route.startswith(LOCAL_ROUTE_PREFIXES)
            and handling.get("policy") not in CLOUD_SAFE_POLICIES):
        raise ModelPolicyBlocked("provider_may_train",
                                 "this provider may use prompts for training")
    return handling


def _guardrails_mode(orch: Any) -> str:
    security = getattr(orch, "security", None) if orch is not None else None
    if security is None:
        return "off"
    try:
        return str(security.stats().get("mode", "off"))
    except Exception:  # a posture read must never fail the page that asks for it
        logger.warning("guardrails mode unreadable; reporting it as unknown")
        return "unknown"


def _posture(available: bool, *, policy: str, reason: str = "", backend: str = "",
             model: str = "", route: str = "", locality: str = "unknown",
             guardrails_mode: str = "off") -> dict:
    return {"available": available, "backend": backend, "model": model, "route": route,
            "locality": locality, "policy": policy, "reason": reason,
            "guardrails_mode": guardrails_mode}


class HubEngine:
    """The real engine: the hub's router, guardrails and data-handling gate."""

    async def complete(self, *, system: str, prompt: str, policy: str, max_tokens: int,
                       temperature: float, on_token: Callable[[str], Awaitable[None]] | None,
                       timeout_seconds: float) -> LLMResult:
        """Appendix A steps 1–6; the reply check (step 7) is done by :func:`complete`."""
        policy = normalize_policy(policy)
        orch, router = _hub()
        backend, model, route = _select(router, policy, prompt, preview=False)
        handling = _authorize(router, backend, model, route, policy, actual_use=True)
        locality = route_locality(handling.get("policy"), route)
        guarded = bind_guardrails(getattr(orch, "security", None), backend)
        started = time.monotonic()
        text = await self._generate(router, guarded, backend, model, system=system,
                                    prompt=prompt, max_tokens=max_tokens,
                                    temperature=temperature, on_token=on_token,
                                    timeout_seconds=timeout_seconds)
        latency_ms = int((time.monotonic() - started) * 1000)
        return LLMResult(text=text, model=model, route=route, locality=locality,
                         latency_ms=latency_ms)

    @staticmethod
    async def _generate(router: Any, guarded: Any, backend: Any, model: str, *, system: str,
                        prompt: str, max_tokens: int, temperature: float,
                        on_token: Callable[[str], Awaitable[None]] | None,
                        timeout_seconds: float) -> str:
        """Appendix A step 6: the guarded stream inside the physical-request scope.

        The scope re-checks data handling on every HTTP request the backend sends and
        re-raises a refusal when it closes, even though the backend itself swallowed it
        into a degraded reply — hence the ``except`` outside the ``with``.
        """
        def recheck() -> dict:
            return router.check_data_handling(backend, model)

        try:
            with physical_request_scope(recheck):
                return await bounded(
                    guarded.generate_stream(model=model, prompt=prompt, system=system,
                                            max_tokens=max_tokens, temperature=temperature,
                                            on_token=on_token),
                    what="workspace model", seconds=timeout_seconds,
                )
        except DataHandlingRefused as exc:
            raise ModelPolicyBlocked("data_policy_unacknowledged") from exc
        except SecurityBlockError as exc:
            raise ContentBlocked() from exc
        except BackendTimeout as exc:
            raise ModelTimeout(timeout_seconds) from exc
        except ModelNotApprovedError as exc:
            raise LLMUnavailable("model_not_approved") from exc
        except RuntimeError as exc:
            logger.warning("workspace model call failed: %s", type(exc).__name__)
            raise LLMUnavailable("backend_error") from exc

    async def posture(self, policy: str) -> dict:
        """What the next call would use, without sending anything (Appendix A ``posture``)."""
        policy = normalize_policy(policy)
        orch = app_state.get_orch()
        mode = _guardrails_mode(orch)
        try:
            _, router = _hub()
            backend, model, route = _select(router, policy, "x", preview=True)
        except WorkspaceError as exc:
            return _posture(False, policy=policy, reason=str(exc.extra.get("reason", exc.code)),
                            guardrails_mode=mode)
        try:
            handling = _authorize(router, backend, model, route, policy, actual_use=False)
        except WorkspaceError as exc:
            return _posture(False, policy=policy, reason=str(exc.extra.get("reason", exc.code)),
                            model=model, route=route, locality=route_locality(None, route),
                            guardrails_mode=mode)
        return _posture(True, policy=policy, backend=str(handling.get("provider") or ""),
                        model=model, route=route,
                        locality=route_locality(handling.get("policy"), route),
                        guardrails_mode=mode)


_HUB_ENGINE = HubEngine()
_engine_override: Engine | None = None


def set_engine_for_tests(engine: Engine | None) -> None:
    """Install a test double (``None`` restores the real :class:`HubEngine`)."""
    global _engine_override
    _engine_override = engine


def _engine() -> Engine:
    return _engine_override if _engine_override is not None else _HUB_ENGINE


# ── concurrency ──────────────────────────────────────────────────────────────────────

# asyncio primitives belong to one event loop, and the hub runs one; test clients start a
# loop per request, so the semaphore is kept per loop. A changed size takes effect for new
# callers at once — holders of the old semaphore release the one they acquired.
_slots: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, tuple[int, asyncio.Semaphore]] = (
    weakref.WeakKeyDictionary())
_slots_lock = threading.Lock()


def _semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    size = config.max_concurrent_llm()
    with _slots_lock:
        entry = _slots.get(loop)
        if entry is None or entry[0] != size:
            entry = (size, asyncio.Semaphore(size))
            _slots[loop] = entry
        return entry[1]


@asynccontextmanager
async def model_slot() -> AsyncIterator[None]:
    """Hold one of the ``NERVA_WORKSPACE_MAX_CONCURRENT_LLM`` slots; 30 s → ``model_busy``."""
    semaphore = _semaphore()
    try:
        async with asyncio.timeout(ACQUIRE_TIMEOUT_SECONDS):
            await semaphore.acquire()
    except TimeoutError as exc:
        logger.warning("workspace model busy: no slot within %.0f s", ACQUIRE_TIMEOUT_SECONDS)
        raise ModelBusy() from exc
    try:
        yield
    finally:
        semaphore.release()


# ── streaming hold-back ──────────────────────────────────────────────────────────────

class TokenGate:
    """Holds the start of a streamed answer until it cannot be a backend failure reply.

    Backends report failures as ordinary text (``⚠️ I can't reach the local …``) and
    stream it like an answer. The first :data:`HOLD_BACK_CHARS` characters are held;
    if they read as a failure reply nothing is ever forwarded. A failure appended
    after a partial answer (a stream that broke midway) is dropped the same way.
    Whatever is still held when the answer succeeds is released by :meth:`finish`.
    Forwarded text is :func:`clean_text`-ed; a high surrogate ending one piece waits for
    the next, so an emoji split across chunks reaches the user whole.
    """

    def __init__(self, sink: TokenSink) -> None:
        self._sink = sink
        self._held = ""
        self._carry = ""
        self._released = False
        self._muted = False

    async def feed(self, token: str) -> None:
        """The backend's ``on_token`` (an ``async def``: ``base._emit`` requires one).

        A backend emits its failure reply as one piece, also after a partial answer
        (a stream that broke midway), so each piece is checked on its own as well as
        the held start: a short partial answer plus the failure must not add up to
        64 characters that get released.
        """
        if self._muted or not isinstance(token, str) or not token:
            return
        if is_backend_failure_reply(token.lstrip()):
            self._mute()
            return
        if self._released:
            await self._forward(token)
            return
        self._held += token
        if len(self._held) < HOLD_BACK_CHARS:
            return
        if is_backend_failure_reply(self._held.lstrip()):
            self._mute()
            return
        await self._release()

    def _mute(self) -> None:
        self._muted = True
        self._held = ""

    async def finish(self) -> None:
        """Release what is still held — called only once the answer is known good."""
        if not self._muted and self._held:
            await self._release()
        if not self._muted and self._carry:
            carry, self._carry = self._carry, ""
            await self._emit(clean_text(carry))

    async def _release(self) -> None:
        held, self._held = self._held, ""
        self._released = True
        await self._forward(held)

    async def _forward(self, text: str) -> None:
        text = self._carry + text
        self._carry = ""
        if text and _HIGH_SURROGATES[0] <= text[-1] <= _HIGH_SURROGATES[1]:
            self._carry, text = text[-1], text[:-1]
        if text:
            await self._emit(clean_text(text))

    async def _emit(self, text: str) -> None:
        outcome = self._sink(text)
        if inspect.isawaitable(outcome):
            await outcome


def _check_reply(result: LLMResult) -> None:
    """Appendix A step 7: a degraded reply or an empty answer is a failure, not an answer."""
    text = result.text if isinstance(result.text, str) else ""
    meta = {"model": result.model, "route": result.route, "locality": result.locality,
            "latency_ms": result.latency_ms}
    if text == THINKING_EXHAUSTED_REPLY:
        raise LLMUnavailable("thinking_exhausted",
                             "the model used its whole budget thinking", **meta)
    if is_backend_failure_reply(text.lstrip()):
        raise LLMUnavailable("model_error", "the model server answered with an error", **meta)
    if not text.strip():
        raise LLMUnavailable("empty_answer", "the model returned an empty answer", **meta)


# ── public API ───────────────────────────────────────────────────────────────────────

async def complete(*, system: str, prompt: str, policy: str, max_tokens: int = 1200,
                   temperature: float = 0.2,
                   on_token: Callable[[str], Awaitable[None]] | None = None,
                   timeout_seconds: float = 180.0) -> LLMResult:
    """Answer *prompt* under the organisation's *policy*; stream through *on_token*.

    Raises :class:`LLMUnavailable`, :class:`ModelPolicyBlocked`, :class:`ModelBusy`,
    :class:`ModelTimeout` or :class:`ContentBlocked` — never returns a failure string.
    *timeout_seconds* bounds the answer itself; waiting for a free slot has its own
    30 s bound.
    """
    gate = TokenGate(on_token) if on_token is not None else None
    async with model_slot():
        result = await _engine().complete(
            system=system, prompt=prompt, policy=normalize_policy(policy),
            max_tokens=max_tokens, temperature=temperature,
            on_token=gate.feed if gate is not None else None, timeout_seconds=timeout_seconds,
        )
    if isinstance(result.text, str):
        result.text = clean_text(result.text)
    _check_reply(result)
    if gate is not None:
        await gate.finish()
    return result


async def posture(policy: str) -> dict:
    """``{available, backend, model, route, locality, policy, reason, guardrails_mode}``.

    A posture read must never fail the page that asks for it: an unforeseen engine
    fault reads as an unavailable model (``backend_error``), logged by type only.
    """
    normalized = normalize_policy(policy)
    try:
        return await _engine().posture(normalized)
    except Exception as exc:
        logger.warning("workspace model posture failed: %s", type(exc).__name__)
        return _posture(False, policy=normalized, reason="backend_error",
                        guardrails_mode="unknown")
