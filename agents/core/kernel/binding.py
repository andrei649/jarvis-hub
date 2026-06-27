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


def make_action_kernel(orch):
    """Return a bound ``kernel.authorize`` (a ``functools.partial``) for *orch*, or
    ``None`` if no autonomy policy is reachable (brokers then run kernel-less).

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
    )
