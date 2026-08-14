"""kernel/binding.py — build the bound ``kernel.authorize`` for the in-process brokers.

One definition of how a broker's ``kernel=`` hook is constructed from the live
orchestrator, so the **single source of truth** for what the kernel front door is
bound to (kill-switch · capabilities · policy · audit→IntentLog) lives in one place
and both call sites stay in lock-step:

  * the **autonomy coordinator** binds it into the wave-1 brokers
    (writeback / social / call / node), and
  * **web.py** binds the same hook into the ``PaymentBroker`` singleton
    (the payment micro-wave).

Returns ``None`` when the autonomy policy isn't available → brokers stay
kernel-less and behave exactly as before. Default-OFF at runtime regardless:
the brokers only *call* the hook when ``JARVIS_ACTION_KERNEL`` is set
(see ``flags.kernel_enabled``), so binding it changes nothing until enabled.
"""

from __future__ import annotations

import functools
import os
import threading
from contextvars import ContextVar
from copy import deepcopy

from ..action_origin import current_action_origin
from .budget import BudgetLedger, BudgetLimits

_BUDGET_ENV = {
    "max_tokens": "JARVIS_BUDGET_MAX_TOKENS",
    "max_wall_seconds": "JARVIS_BUDGET_MAX_WALL_SECONDS",
    "max_depth": "JARVIS_BUDGET_MAX_DEPTH",
}


class _OneShotDecision:
    """A pending decision shared by every copied async context, consumed once."""

    def __init__(self, action, decision) -> None:
        self._action = action
        self._decision = decision
        self._consumed = False
        self._lock = threading.Lock()

    def take(self):
        with self._lock:
            if self._consumed:
                return None
            self._consumed = True
            return self._action, self._decision


class MediationKernelBridge:
    """One-use handoff from a broker kernel call to its immediate queue insert.

    Brokers already call the Action Kernel before invoking their enqueue sink.  B7
    must persist that exact decision without calling the kernel a second time (which
    could consume budgets or trip the loop detector).  The bridge keeps the last
    decision in the current async/thread context and releases it only when the worker
    presents the exact same immutable :class:`Action`.
    """

    def __init__(self, kernel) -> None:
        self._kernel = kernel
        self._pending = ContextVar(f"mediation_kernel_decision_{id(self)}", default=None)

    def __call__(self, action, capability=None, budget=None):
        if not callable(self._kernel):
            raise RuntimeError("action kernel is unavailable")
        self._pending.set(None)
        try:
            authorized_action = deepcopy(action)
        except Exception as exc:
            raise RuntimeError("action could not be snapshotted for mediation") from exc
        if capability is None and budget is None:
            decision = self._kernel(action)
        elif budget is None:
            decision = self._kernel(action, capability)
        else:
            decision = self._kernel(action, capability=capability, budget=budget)
        self._pending.set(_OneShotDecision(authorized_action, decision))
        return decision

    def consume(self, action):
        pending = self._pending.get()
        self._pending.set(None)
        released = pending.take() if isinstance(pending, _OneShotDecision) else None
        if released is None or released[0] != action:
            return None
        return released[1]

    def consume_for_enqueue(self, *, agent, kind, title, payload, origin):
        """Release a broker decision matching the exact persisted task fields.

        ``Action.scope`` is deliberately returned from the broker record rather than
        guessed by the generic queue sink (node dispatch uses ``node:<id>``).
        """

        pending = self._pending.get()
        self._pending.set(None)
        released = pending.take() if isinstance(pending, _OneShotDecision) else None
        if released is None:
            return None
        action, decision = released
        if (
            action.agent != agent
            or action.kind != kind
            or action.title != title
            or action.payload != payload
            or action.origin != origin
        ):
            return None
        return action, decision


def make_budget_ledger(config: dict | None = None, *, env=None) -> BudgetLedger | None:
    """Build a per-task :class:`BudgetLedger` from limits, or ``None`` if none set.

    Limits are read from *config* (a dict with any of ``max_tokens`` /
    ``max_wall_seconds`` / ``max_depth``) first, then from the environment
    (``JARVIS_BUDGET_MAX_TOKENS`` / ``_MAX_WALL_SECONDS`` / ``_MAX_DEPTH``). A
    missing/blank/unparseable value leaves that dimension unlimited. When **all
    three** are unset the function returns ``None`` — the caller then enforces
    nothing, preserving the default-off contract (no budget enforcement unless a
    limit is explicitly configured)."""
    env = os.environ if env is None else env
    cfg = config if isinstance(config, dict) else {}

    def _read(key, cast):
        v = cfg.get(key)
        if v is None:
            v = env.get(_BUDGET_ENV[key])
        if v is None or v == "":
            return None
        try:
            return cast(v)
        except (TypeError, ValueError):
            return None

    max_tokens = _read("max_tokens", int)
    max_wall = _read("max_wall_seconds", float)
    max_depth = _read("max_depth", int)
    if max_tokens is None and max_wall is None and max_depth is None:
        return None
    return BudgetLedger(
        limits=BudgetLimits(max_tokens=max_tokens, max_wall_seconds=max_wall, max_depth=max_depth)
    )


def make_action_kernel(orch, *, loop_detector=None, budget_ledger=None):
    """Return a bound ``kernel.authorize`` (a ``functools.partial``) for *orch*, or
    ``None`` if no autonomy policy is reachable (brokers then run kernel-less).

    ``loop_detector`` (K3) is **opt-in** and bound only by callers that want the
    loop-wide circuit breaker — today just the autonomy coordinator (the broker action
    path). Route/egress callers omit it, because the breaker keys on ``action.kind`` and
    those paths legitimately repeat the same kind (many egress calls / KG writes) and
    would false-trip. ``None`` → the breaker is inert (K1 behavior).

    ``budget_ledger`` is likewise optional; callers that supply it share one K3 budget
    view across brokers/executors while callers that omit it remain byte-identical.

    The import of ``authorize`` is local so this module stays cheap and cycle-free
    (a broker importing ``binding`` must not pull the whole kernel/autonomy graph).
    """
    from . import authorize as _authorize_action

    pol = getattr(getattr(orch, "autonomy", None), "policy", None) or getattr(
        orch, "autonomy_policy", None
    )
    if pol is None:
        return None
    return functools.partial(
        _authorize_action,
        kill_switch=getattr(orch, "kill_switch", None),
        capabilities=getattr(orch, "capabilities", None),
        policy=pol,
        audit=getattr(orch, "intent_log", None),
        loop_detector=loop_detector,
        budget_ledger=budget_ledger,
    )


def make_egress_kernel_hook(get_kernel):
    """Adapt a bound ``kernel.authorize`` to the ``http_client`` egress-hook signature
    ``(plugin, method, url, host) -> reason|None`` (wave-2 plugin-egress mediation).

    *get_kernel* is the bound kernel.authorize, or a zero-arg callable returning it (or
    ``None``) — evaluated **lazily** per call so it reads live orchestrator state
    (kill-switch / policy may be wired after this hook is installed). Returns a
    deny-reason string when the kernel DENYs an otherwise-allowed egress, else ``None``.
    Default-off: returns ``None`` immediately unless ``JARVIS_ACTION_KERNEL`` is set, so
    installing it changes nothing at runtime until enabled.
    """
    from . import Action, Verdict, kernel_enabled

    def _hook(plugin, method, url, host):
        if not kernel_enabled():
            return None
        k = get_kernel() if callable(get_kernel) else get_kernel
        if k is None:
            return None
        decision = k(
            Action(
                kind="plugin.egress",
                agent=plugin or "plugin",
                title=f"egress {method} {host}",
                payload={"plugin": plugin, "method": method, "host": host, "url": url},
                origin=current_action_origin(),
            )
        )
        return decision.reason if decision.verdict is Verdict.DENY else None

    return _hook
