"""host_requests.py — what Nerva answers when an MCP server asks *it* something (H553).

The MCP spec lets a server send requests back to its client in the middle of a call. Two
of them reach the owner's money or the owner's attention, so neither is answered on the
server's say-so:

**Sampling** (``sampling/createMessage``): the server wants an LLM completion.

* Off unless the owner turns it on per server (``sampling: "ask"`` or ``"auto"``).
  ``ask`` puts an approval card in the owner's queue and answers only after an approval;
  ``auto`` answers without a card, still inside every limit below.
* It is charged to the owner's budget: a :class:`~agents.core.kernel.budget.BudgetLedger`
  dimension ``mcp_sampling_tokens`` with a daily ceiling (``JARVIS_MCP_SAMPLING_DAILY_TOKENS``,
  default 20 000 estimated tokens), reserved before the call and settled after it. Over
  the ceiling the request is refused before any card is shown. The ledger is the K3
  primitive held in memory by this host: it resets when Nerva restarts (and at UTC
  midnight); it is not written to disk.
* Per-server limits: a 60-second sliding-window rate limit (``max_rpm``, default 10; the
  same rule as Hermes ``SamplingHandler._check_rate_limit``, written natively), an output
  cap (``max_tokens_cap``, default and ceiling 1024) and a timeout (default 30 s).
* **Never with tools.** A request that carries ``tools`` or ``toolChoice`` is refused, and
  Nerva never declares the ``sampling.tools`` capability. The completion runs stateless on
  the local auxiliary rail: no history, no memory, no tool, nothing written to a session.
* The server's ``modelPreferences`` are mapped onto a Nerva model role, never onto a model
  name the server picks: ``capable`` (the auxiliary ``review`` task's model) when the
  server's intelligence priority leads, otherwise ``fast`` (the auxiliary one-shot model).
  A hint that names a role is honoured; any other hint is ignored. The owner can pin a
  role (``role``) or narrow the set (``allowed_roles``). The answer names the role
  (``nerva-fast``), not the local model.

**Elicitation** (``elicitation/create``): the server wants input from the person.

* Off unless the owner turns it on for the server (``elicitation: true``), at most 3 cards
  a minute per server and 2 server requests per client call.
* Every server-chosen string on a card (message, field names, descriptions, enum values,
  a sampling request's text) goes through ``subagents.card_safe``: no newline, ANSI,
  bidi or zero-width trick can make it look like Nerva's own words.
* The wait sits in a native human-wait window, so the tool loop's deadline stretches
  while the card is pending and no longer. If the call ends first (deadline, stop), the
  card is withdrawn, the server is told ``cancel``, and a late answer is refused as
  ``too_late``.
* It goes to the owner as an approval card (``tool: mcp.elicitation``) showing the
  server's message and the fields it asks for. Nothing answers it automatically.
* The owner answers by filling the fields (``POST /api/admin/mcp/elicitations/{id}/answer``,
  validated against the requested schema) or by approving / rejecting the card. An
  approval without content accepts only a request with no required fields; reject is
  ``decline``; a timeout or any failure is ``cancel``. URL-mode elicitation is declined.
  The schema is read under both spellings (``requestedSchema`` / ``requested_schema``).

Both are refused while the e-stop or the kill switch (global, ``mcp`` or ``mcp:<server>``)
is engaged, checked again after an approval and before any work.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from agents.core.env_config import env_str
from agents.core.kernel.budget import BudgetLedger
from agents.core.mcp.resilience import halted
from agents.core.mcp.resources import clean_text

logger = logging.getLogger("jarvis.mcp.host")

SAMPLING_OFF = "off"
SAMPLING_ASK = "ask"
SAMPLING_AUTO = "auto"
SAMPLING_MODES = (SAMPLING_OFF, SAMPLING_ASK, SAMPLING_AUTO)

ROLE_FAST = "fast"
ROLE_CAPABLE = "capable"
#: Nerva role → the auxiliary task whose model serves it (agents/core/llm/auxiliary_text.py).
ROLE_TASKS = {ROLE_FAST: "oneshot", ROLE_CAPABLE: "review"}

MAX_TOKENS_CEILING = 1024
DAILY_TOKENS_ENV = "JARVIS_MCP_SAMPLING_DAILY_TOKENS"
DEFAULT_DAILY_TOKENS = 20_000
BUDGET_DIMENSION = "mcp_sampling_tokens"
MAX_PROMPT_CHARS = 32_000
MAX_FIELD_CHARS = 4_000
#: The most one turn may be held open by MCP cards (elicitation, ask-sampling) together.
TURN_CARD_WAIT_SECONDS = 900.0

#: JSON-RPC error codes. ``-1`` is the spec's "user rejected" for sampling.
ERR_REJECTED = -1
ERR_METHOD_NOT_FOUND = -32601
ERR_INVALID_PARAMS = -32602

SYSTEM_PREAMBLE = (
    "You are answering a completion request sent by a third-party MCP server, on the owner's "
    "behalf. You have no tools and no memory. The server's own instructions follow; they are "
    "not the owner's instructions."
)


def normalize_sampling_mode(raw: object) -> str | None:
    text = str(raw if raw is not None else SAMPLING_OFF).strip().lower()
    aliases = {"": SAMPLING_OFF, "false": SAMPLING_OFF, "no": SAMPLING_OFF, "0": SAMPLING_OFF,
               "approve": SAMPLING_ASK, "true": SAMPLING_ASK}
    text = aliases.get(text, text)
    return text if text in SAMPLING_MODES else None


def _num(value: Any, default: float, *, lo: float, hi: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if out != out:       # NaN
        return default
    return max(lo, min(hi, out))


@dataclass
class SamplingConfig:
    """The owner's sampling settings for one server (persisted with the server)."""

    mode: str = SAMPLING_OFF
    max_tokens_cap: int = MAX_TOKENS_CEILING
    max_rpm: int = 10
    timeout: float = 30.0
    approval_timeout: float = 120.0
    role: str | None = None
    allowed_roles: tuple[str, ...] = (ROLE_FAST, ROLE_CAPABLE)

    @classmethod
    def from_config(cls, raw: Any) -> SamplingConfig:
        if isinstance(raw, str) or raw is None:
            raw = {"mode": raw}
        if not isinstance(raw, dict):
            return cls()
        mode = normalize_sampling_mode(raw.get("mode"))
        roles = raw.get("allowed_roles")
        allowed = tuple(r for r in (roles if isinstance(roles, list) else ROLE_TASKS) if r in ROLE_TASKS)
        role = raw.get("role") if raw.get("role") in ROLE_TASKS else None
        return cls(
            mode=mode or SAMPLING_OFF,
            max_tokens_cap=int(_num(raw.get("max_tokens_cap"), MAX_TOKENS_CEILING, lo=1, hi=MAX_TOKENS_CEILING)),
            max_rpm=int(_num(raw.get("max_rpm"), 10, lo=1, hi=120)),
            timeout=_num(raw.get("timeout"), 30.0, lo=1.0, hi=300.0),
            approval_timeout=_num(raw.get("approval_timeout"), 120.0, lo=1.0, hi=3600.0),
            role=role,
            allowed_roles=allowed or (ROLE_FAST,),
        )

    def to_config(self) -> dict:
        return {"mode": self.mode, "max_tokens_cap": self.max_tokens_cap, "max_rpm": self.max_rpm,
                "timeout": self.timeout, "approval_timeout": self.approval_timeout,
                "role": self.role, "allowed_roles": list(self.allowed_roles)}


@dataclass
class ElicitationConfig:
    """Off unless the owner turns it on for the server, like sampling: each request puts a
    card in front of the owner, so a server may not do that on its own say-so."""

    enabled: bool = False
    timeout: float = 300.0
    max_per_minute: int = 3

    @classmethod
    def from_config(cls, raw: Any) -> ElicitationConfig:
        if isinstance(raw, bool):
            return cls(enabled=raw)
        if not isinstance(raw, dict):
            return cls()
        return cls(enabled=raw.get("enabled") is True,
                   timeout=_num(raw.get("timeout"), 300.0, lo=1.0, hi=3600.0),
                   max_per_minute=int(_num(raw.get("max_per_minute"), 3, lo=1, hi=30)))

    def to_config(self) -> dict:
        return {"enabled": self.enabled, "timeout": self.timeout,
                "max_per_minute": self.max_per_minute}


class RateLimiter:
    """Sliding 60-second window per server."""

    def __init__(self, window: float = 60.0) -> None:
        self.window = window
        self._stamps: dict[str, list[float]] = {}

    def admit(self, server: str, limit: int, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        stamps = [t for t in self._stamps.get(server, []) if t > now - self.window]
        if len(stamps) >= limit:
            self._stamps[server] = stamps
            return False
        stamps.append(now)
        self._stamps[server] = stamps
        return True


class SamplingBudget:
    """The owner's daily allowance for completions MCP servers ask for, on the K3 ledger."""

    def __init__(self, daily_tokens: int | None = None, *, clock: Callable[[], float] = time.time) -> None:
        self._fixed = daily_tokens
        self._clock = clock
        self.ledger = BudgetLedger()
        self._day = ""
        self._roll()

    def limit(self) -> int:
        if self._fixed is not None:
            return int(self._fixed)
        raw = env_str(DAILY_TOKENS_ENV)
        try:
            return max(0, int(raw)) if raw else DEFAULT_DAILY_TOKENS
        except ValueError:
            return DEFAULT_DAILY_TOKENS

    def _roll(self) -> None:
        day = datetime.fromtimestamp(self._clock(), UTC).strftime("%Y-%m-%d")
        dim = self.ledger.dimensions.get(BUDGET_DIMENSION)
        used = 0.0 if (day != self._day or dim is None) else dim.used
        self._day = day
        self.ledger.set_dimension_usage(BUDGET_DIMENSION, used, limit=float(self.limit()),
                                        unit="tokens", metadata={"day": day, "scope": "mcp sampling"})

    def reserve(self, tokens: int) -> str | None:
        """Book *tokens* now; a reason string when that would pass the ceiling (nothing booked)."""
        self._roll()
        dim = self.ledger.dimensions[BUDGET_DIMENSION]
        if dim.limit is not None and dim.used + tokens > dim.limit:
            return "budget_exceeded"
        self.ledger.add_dimension_usage(BUDGET_DIMENSION, tokens)
        return None

    def settle(self, reserved: int, actual: int) -> None:
        """Replace a reservation by what the call really cost (estimated)."""
        self._roll()
        dim = self.ledger.dimensions[BUDGET_DIMENSION]
        dim.used = max(0.0, dim.used - reserved + max(0, actual))

    def status(self) -> dict:
        self._roll()
        return self.ledger.dimension_status(BUDGET_DIMENSION)


def estimate_tokens(text: str) -> int:
    """A conservative estimate: four ASCII characters per token, one per other character
    (a CJK character is about one token, so ``len/4`` would undercount it fourfold)."""
    text = text or ""
    wide = sum(1 for ch in text if ord(ch) > 0x7F)
    return max(1, (len(text) - wide + 3) // 4 + wide)


def card_text(value: Any, limit: int) -> str:
    """A server-chosen string made safe to show on an approval card: the same treatment
    as ``subagents.card_safe`` (no control, format, bidi, zero-width, private-use
    character, no square bracket, whitespace collapsed), then cut to *limit*."""
    from agents.core.subagents import card_safe

    text = card_safe(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def map_model_preferences(prefs: Any, cfg: SamplingConfig) -> str:
    """A server's ``modelPreferences`` → a Nerva role the owner allows for this server."""
    if cfg.role in cfg.allowed_roles:
        return cfg.role
    wanted = ROLE_FAST
    if isinstance(prefs, dict):
        hinted = [h.get("name") for h in prefs.get("hints") or [] if isinstance(h, dict)]
        named = next((h for h in hinted if h in ROLE_TASKS), None)
        if named:
            wanted = named
        else:
            intel = _num(prefs.get("intelligencePriority"), 0.0, lo=0.0, hi=1.0)
            cost = _num(prefs.get("costPriority"), 0.0, lo=0.0, hi=1.0)
            speed = _num(prefs.get("speedPriority"), 0.0, lo=0.0, hi=1.0)
            if intel >= 0.5 and intel > max(cost, speed):
                wanted = ROLE_CAPABLE
    if wanted in cfg.allowed_roles:
        return wanted
    return cfg.allowed_roles[0]


def _flatten_messages(messages: Any) -> tuple[str, int]:
    """Sampling messages → one transcript prompt; ``(prompt, dropped_non_text_blocks)``."""
    lines: list[str] = []
    dropped = 0
    for msg in messages if isinstance(messages, list) else []:
        if not isinstance(msg, dict):
            continue
        role = "Assistant" if msg.get("role") == "assistant" else "User"
        content = msg.get("content")
        blocks = content if isinstance(content, list) else [content]
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                lines.append(f"{role}: {clean_text(block['text'])}")
            else:
                dropped += 1
    return "\n\n".join(lines)[:MAX_PROMPT_CHARS], dropped


Generator = Callable[..., Awaitable[str]]


async def default_generator(router: Any, *, role: str, system: str, prompt: str,
                            max_tokens: int, temperature: float) -> str:
    """Stateless local completion on the auxiliary task that serves *role*."""
    from agents.core.llm.auxiliary_text import AuxiliaryBackendFailure, generate_local_auxiliary
    from agents.core.llm.base import is_backend_failure_reply

    if router is None:
        raise RuntimeError("no_model_router")
    answer = await generate_local_auxiliary(router, ROLE_TASKS[role], system=system, prompt=prompt,
                                            max_tokens=max_tokens, temperature=temperature)
    if is_backend_failure_reply(answer):
        raise AuxiliaryBackendFailure("the local model did not answer")
    return answer


def _error(code: int, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


@dataclass
class _PendingElicitation:
    server: str
    schema: dict
    content: dict | None = None


@dataclass
class MCPHost:
    """Host services the MCP client borrows: the approval queue, the model router, the
    kill switch. Each is a zero-argument provider so the host can be built before them."""

    approvals: Callable[[], Any] = lambda: None
    router: Callable[[], Any] = lambda: None
    kill_switch: Callable[[], Any] = lambda: None
    generator: Generator | None = None
    budget: SamplingBudget = field(default_factory=SamplingBudget)
    limiter: RateLimiter = field(default_factory=RateLimiter)
    _elicitations: dict[str, _PendingElicitation] = field(default_factory=dict)
    #: Cards whose call ended before the owner answered: card id → reason (bounded).
    _closed: dict[str, str] = field(default_factory=dict)
    elicit_limiter: RateLimiter = field(default_factory=RateLimiter)

    @staticmethod
    def refusal(method: str, reason: str) -> dict:
        """The answer for a server request Nerva will not serve (or no longer can)."""
        if method == "elicitation/create":
            return {"result": {"action": "cancel"}}
        return _error(ERR_REJECTED, reason)

    def _remember_closed(self, card: str, reason: str) -> None:
        self._closed[card] = reason
        while len(self._closed) > 500:
            self._closed.pop(next(iter(self._closed)))

    def _close_card(self, card: str | None, reason: str) -> None:
        """Withdraw a card whose request is gone, so an answer cannot land on nothing."""
        if not card:
            return
        self._elicitations.pop(card, None)
        self._remember_closed(card, reason)
        queue = self.approvals()
        try:
            item = queue.get(card) if queue is not None else None
            if item and item.get("status") == "pending":
                queue.decide(card, False, by="system", reason=f"withdrawn: {reason}")
        except Exception:
            logger.warning("MCP card %s could not be withdrawn", card, exc_info=True)

    @staticmethod
    def _turn_wait_left(timeout: float) -> float:
        """How long a card may hold this turn: its own timeout, within what is left of the
        turn's MCP card allowance (:data:`TURN_CARD_WAIT_SECONDS`). Outside a tool-loop
        turn there is no turn to hold, so the card's own timeout applies."""
        from agents.core.native_human_wait import current_human_wait_scope

        scope = current_human_wait_scope()
        if scope is None:
            return timeout
        spent = float(getattr(scope, "_mcp_card_seconds", 0.0))
        return max(0.0, min(timeout, TURN_CARD_WAIT_SECONDS - spent))

    async def _await_card(self, queue: Any, card: str, timeout: float) -> str:
        """Wait for the owner, inside a native human-wait window: the tool loop's deadline
        is extended while the card is pending (``native_human_wait``), and only then. The
        time is charged to the turn's MCP card allowance."""
        from agents.core.native_human_wait import current_human_wait_scope, native_human_wait_window

        scope = current_human_wait_scope()
        started = time.monotonic()
        try:
            return await self._await_card_window(queue, card, timeout, native_human_wait_window)
        finally:
            if scope is not None:
                spent = float(getattr(scope, "_mcp_card_seconds", 0.0))
                scope._mcp_card_seconds = spent + (time.monotonic() - started)

    @staticmethod
    async def _await_card_window(queue: Any, card: str, timeout: float, window: Any) -> str:
        def current() -> bool:
            try:
                item = queue.get(card)
            except Exception:
                return False
            return bool(item) and item.get("status") == "pending"

        with window(deadline=time.monotonic() + timeout, current=current):
            return await queue.await_decision(card, timeout=timeout)

    # ── capability declaration ───────────────────────────────────────────

    def client_capabilities(self, sampling: SamplingConfig, elicitation: ElicitationConfig) -> dict:
        """What ``initialize`` declares: only what this host can really answer."""
        caps: dict[str, Any] = {}
        if sampling.mode != SAMPLING_OFF:
            caps["sampling"] = {}            # never ``{"tools": {}}``
        if elicitation.enabled and self.approvals() is not None:
            caps["elicitation"] = {"form": {}}
        return caps

    def _halted(self, server: str) -> str | None:
        return halted(self.kill_switch(), "mcp", server=server)

    # ── dispatch ─────────────────────────────────────────────────────────

    async def handle(self, server: Any, method: str, params: Any) -> dict:
        """Answer one server-initiated request: ``{"result": …}`` or ``{"error": …}``."""
        params = params if isinstance(params, dict) else {}
        health = getattr(server, "health", None)
        if method == "ping":
            return {"result": {}}
        if method == "sampling/createMessage":
            out = await self._sampling(server, params)
            if health is not None:
                health.bump("sampling_answered" if "result" in out else "sampling_refused")
            return out
        if method == "elicitation/create":
            out = await self._elicitation(server, params)
            if health is not None:
                health.bump(f"elicitation_{(out.get('result') or {}).get('action', 'error')}")
            return out
        return _error(ERR_METHOD_NOT_FOUND, f"method not supported by this client: {method[:80]}")

    # ── sampling ─────────────────────────────────────────────────────────

    async def _ask(self, tool: str, server: str, args: dict, summary: str,
                   timeout: float) -> tuple[str, str | None]:
        """Put a card in the owner's queue and wait; ``(status, card_id)``."""
        queue = self.approvals()
        if queue is None:
            return "no_approval_queue", None
        timeout = self._turn_wait_left(timeout)
        if timeout < 1.0:
            return "turn_wait_exhausted", None
        item = queue.request({"tool": tool, "args": args, "agent": f"mcp:{server}",
                              "summary": summary, "risk_tier": 2})
        card = item.get("id")
        try:
            status = await self._await_card(queue, card, timeout)
        except asyncio.CancelledError:
            self._close_card(card, "the MCP call that asked has ended")
            raise
        return status, card

    async def _sampling(self, server: Any, params: dict) -> dict:
        name = getattr(server, "name", "?")
        cfg: SamplingConfig = getattr(server, "sampling", None) or SamplingConfig()
        if cfg.mode == SAMPLING_OFF:
            return _error(ERR_REJECTED, "sampling is not enabled for this server")
        stop = self._halted(name)
        if stop:
            return _error(ERR_REJECTED, f"refused: {stop}")
        if params.get("tools") or params.get("toolChoice") or params.get("tool_choice"):
            return _error(ERR_INVALID_PARAMS, "sampling with tools is not supported by this client")
        if not self.limiter.admit(name, cfg.max_rpm):
            return _error(ERR_REJECTED, f"rate limit: {cfg.max_rpm} requests/minute")
        prompt, dropped = _flatten_messages(params.get("messages"))
        if not prompt.strip():
            return _error(ERR_INVALID_PARAMS, "no text messages to answer")
        server_system = clean_text(params.get("systemPrompt") or "")[:4000]
        system = SYSTEM_PREAMBLE + ("\n\n" + server_system if server_system else "")
        requested = params.get("maxTokens")
        max_tokens = int(_num(requested, cfg.max_tokens_cap, lo=1, hi=cfg.max_tokens_cap))
        role = map_model_preferences(params.get("modelPreferences"), cfg)
        reserve = estimate_tokens(system) + estimate_tokens(prompt) + max_tokens
        over = self.budget.reserve(reserve)
        if over:
            return _error(ERR_REJECTED, f"refused: {over}")
        settled = False
        try:
            if cfg.mode == SAMPLING_ASK:
                status, _card = await self._ask(
                    "mcp.sampling", name,
                    {"server": name, "role": role, "max_tokens": max_tokens,
                     "system_prompt": card_text(server_system, 1000),
                     "messages": card_text(prompt, 2000), "untrusted": True},
                    f"MCP server '{name}' asks for a model completion (up to {max_tokens} tokens)",
                    cfg.approval_timeout,
                )
                if status != "approved":
                    self.budget.settle(reserve, 0)
                    settled = True
                    return _error(ERR_REJECTED, f"not approved: {status}")
                stop = self._halted(name)
                if stop:
                    self.budget.settle(reserve, 0)
                    settled = True
                    return _error(ERR_REJECTED, f"refused: {stop}")
            temperature = _num(params.get("temperature"), 0.2, lo=0.0, hi=2.0)
            generate = self.generator or (lambda **kw: default_generator(self.router(), **kw))
            answer = await asyncio.wait_for(
                generate(role=role, system=system, prompt=prompt, max_tokens=max_tokens,
                         temperature=temperature),
                timeout=cfg.timeout,
            )
        except TimeoutError:
            if not settled:
                self.budget.settle(reserve, estimate_tokens(system) + estimate_tokens(prompt))
            return _error(ERR_REJECTED, "sampling timed out")
        except asyncio.CancelledError:
            if not settled:
                self.budget.settle(reserve, 0)
            raise
        except Exception as exc:
            logger.warning("MCP %s sampling failed (%s)", name, type(exc).__name__)
            if not settled:
                self.budget.settle(reserve, 0)
            return _error(ERR_REJECTED, "sampling failed")
        text = str(answer or "")
        spent = estimate_tokens(system) + estimate_tokens(prompt) + estimate_tokens(text)
        self.budget.settle(reserve, spent)
        health = getattr(server, "health", None)
        if health is not None:
            health.bump("sampling_tokens", spent)
        result: dict[str, Any] = {"role": "assistant", "content": {"type": "text", "text": text},
                                  "model": f"nerva-{role}", "stopReason": "endTurn"}
        if dropped:
            result["_meta"] = {"nerva/droppedNonTextBlocks": dropped}
        return {"result": result}

    # ── elicitation ──────────────────────────────────────────────────────

    async def _elicitation(self, server: Any, params: dict) -> dict:
        name = getattr(server, "name", "?")
        cfg: ElicitationConfig = getattr(server, "elicitation", None) or ElicitationConfig()

        def answer(action: str, content: dict | None = None) -> dict:
            body: dict[str, Any] = {"action": action}
            if action == "accept":
                body["content"] = content or {}
            return {"result": body}

        if not cfg.enabled:
            return answer("decline")
        if params.get("mode") == "url":
            return answer("decline")
        if self._halted(name):
            return answer("decline")
        schema = params.get("requestedSchema") or params.get("requested_schema") or {}
        if not isinstance(schema, dict):
            return answer("decline")
        if not schema_is_clean(schema):
            # A field name or choice the card would have to clean is one the owner could
            # not answer exactly (the cleaned text is not the server's key): decline.
            return answer("decline")
        # Cards still open count against the rate too: a slow owner is not a free pass.
        open_here = sum(1 for p in self._elicitations.values() if p.server == name)
        if open_here >= cfg.max_per_minute or not self.elicit_limiter.admit(name, cfg.max_per_minute):
            return answer("decline")
        wait = self._turn_wait_left(cfg.timeout)
        if wait < 1.0:
            return answer("decline")             # the turn's card allowance is used up
        message = card_text(params.get("message") or "", 500)
        fields = describe_fields(schema)
        queue = self.approvals()
        if queue is None:
            return answer("cancel")
        card = None
        try:
            item = queue.request({
                "tool": "mcp.elicitation", "agent": f"mcp:{name}",
                "args": {"server": name, "message": message, "fields": fields,
                         "required": [card_text(r, 100) for r in _required(schema)],
                         "untrusted": True},
                "summary": f"MCP server '{card_text(name, 64)}' asks you for input: {message[:160]}",
                "risk_tier": 2,
            })
            card = item.get("id")
            self._elicitations[card] = _PendingElicitation(server=name, schema=schema)
            status = await self._await_card(queue, card, wait)
        except asyncio.CancelledError:
            pending = self._elicitations.get(card) if card else None
            if pending is not None and pending.content is not None:
                # The owner's answer crossed the cancellation: it was approved and stored,
                # so it is what the server gets (the client writes it), not a cancel.
                server._cancel_reply = answer("accept", pending.content)
                self._elicitations.pop(card, None)
                self._remember_closed(card, "approved")
            else:
                self._close_card(card, "the MCP call that asked has ended")
            raise
        except Exception:
            logger.warning("MCP %s elicitation card failed", name, exc_info=True)
            self._close_card(card, "failed")
            return answer("cancel")
        pending = self._elicitations.pop(card, None)
        self._remember_closed(card, status)
        if status == "rejected":
            return answer("decline")
        if status != "approved":
            return answer("cancel")
        if self._halted(name):
            return answer("decline")
        content = pending.content if pending is not None else None
        if content is None:
            if _required(schema):
                return answer("decline")
            content = {}
        return answer("accept", content)

    def pending_elicitations(self) -> list[str]:
        return sorted(self._elicitations)

    def answer_elicitation(self, card_id: str, content: Any) -> dict:
        """The owner's typed answer to an elicitation card: validate, store, approve."""
        pending = self._elicitations.get(card_id)
        if pending is None:
            closed = self._closed.get(card_id)
            if closed == "approved":
                return {"ok": False, "error": "already_answered"}
            if closed:
                return {"ok": False, "error": "too_late", "reason": closed}
            return {"ok": False, "error": "unknown_elicitation"}
        if pending.content is not None:
            return {"ok": False, "error": "already_answered"}
        clean, reason = validate_content(pending.schema, content)
        if reason:
            return {"ok": False, "error": reason}
        queue = self.approvals()
        if queue is None:
            return {"ok": False, "error": "no_approval_queue"}
        pending.content = clean
        decided = queue.decide(card_id, True, by="owner")
        if not decided or decided.get("status") != "approved":
            pending.content = None
            return {"ok": False, "error": "card_not_pending"}
        return {"ok": True, "id": card_id, "server": pending.server}


def schema_is_clean(schema: dict) -> bool:
    """Every field name and enum choice is shown on the card exactly as the server sent it:
    no character ``card_text`` would remove or replace."""
    props = schema.get("properties", {})
    if not isinstance(props, dict) or len(props) > 50:
        return False

    def exact(value: Any, limit: int) -> bool:
        return isinstance(value, str) and bool(value) and card_text(value, limit) == value

    for key, spec in props.items():
        if not exact(key, 100):
            return False
        enum = spec.get("enum") if isinstance(spec, dict) else None
        if isinstance(enum, list) and not all(exact(v, 100) for v in enum):
            return False
    return True


def _required(schema: dict) -> list[str]:
    req = schema.get("required")
    return [r for r in req if isinstance(r, str)] if isinstance(req, list) else []


def describe_fields(schema: dict) -> list[dict]:
    props = schema.get("properties") if isinstance(schema, dict) else None
    out = []
    for key, spec in (props.items() if isinstance(props, dict) else []):
        spec = spec if isinstance(spec, dict) else {}
        row = {"name": card_text(key, 100),
               "type": card_text(spec.get("type") or "string", 20)}
        if spec.get("description"):
            row["description"] = card_text(spec["description"], 300)
        if isinstance(spec.get("enum"), list):
            row["enum"] = [card_text(v, 100) for v in spec["enum"][:50]]
        out.append(row)
    return out[:50]


def validate_content(schema: dict, content: Any) -> tuple[dict, str | None]:
    """The owner's answer checked against a flat elicitation schema."""
    if not isinstance(content, dict):
        return {}, "content_not_object"
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    clean: dict[str, Any] = {}
    for key, value in content.items():
        spec = props.get(key)
        if not isinstance(spec, dict):
            return {}, f"unknown_field:{str(key)[:60]}"
        kind = spec.get("type", "string")
        if kind == "boolean":
            ok = isinstance(value, bool)
        elif kind == "integer":
            ok = isinstance(value, int) and not isinstance(value, bool)
        elif kind == "number":
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        else:
            ok = isinstance(value, str) and len(value) <= MAX_FIELD_CHARS
        if not ok:
            return {}, f"bad_type:{str(key)[:60]}"
        if isinstance(spec.get("enum"), list) and value not in spec["enum"]:
            return {}, f"not_in_enum:{str(key)[:60]}"
        clean[key] = value
    missing = [r for r in _required(schema) if r not in clean]
    if missing:
        return {}, f"missing_field:{missing[0][:60]}"
    return clean, None
