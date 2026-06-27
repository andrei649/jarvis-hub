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


def make_action_kernel(orch, *, loop_detector=None):
    """Return a bound ``kernel.authorize`` (a ``functools.partial``) for *orch*, or
    ``None`` if no autonomy policy is reachable (brokers then run kernel-less).

    ``loop_detector`` (K3) is **opt-in** and bound only by callers that want the
    loop-wide circuit breaker — today just the autonomy coordinator (the broker action
    path). Route/egress callers omit it, because the breaker keys on ``action.kind`` and
    those paths legitimately repeat the same kind (many egress calls / KG writes) and
    would false-trip. ``None`` → the breaker is inert (K1 behavior).

    The import of ``authorize`` is local so this module stays cheap and cycle-free
    (a broker importing ``binding`` must not pull the whole kernel/autonomy graph).
    """
    from . import authorize as _authorize_action

    pol = (getattr(getattr(orch, "autonomy", None), "policy", None)
           or getattr(orch, "autonomy_policy", None))
    if pol is None:
        return None
    return functools.partial(
        _authorize_action,
        kill_switch=getattr(orch, "kill_switch", None),
        capabilities=getattr(orch, "capabilities", None),
        policy=pol,
        audit=getattr(orch, "intent_log", None),
        loop_detector=loop_detector,
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
        decision = k(Action(
            kind="plugin.egress", agent=plugin or "plugin",
            title=f"egress {method} {host}",
            payload={"plugin": plugin, "method": method, "host": host, "url": url},
            origin="generated"))
        return decision.reason if decision.verdict is Verdict.DENY else None

    return _hook
