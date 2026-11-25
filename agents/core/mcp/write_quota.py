"""write_quota.py — per-client rate limits on Nerva's MCP write surface (H558 residual).

Nerva's MCP server exposes writes to external clients: the allow-listed mutating route
tools (``route_*``, ``agents/core/mcp/route_tools.py``) and ``approval_respond``
(``inbox_tools.py``). Each already crosses an identity gate, the Action Kernel and a
mandatory audit row; what was missing is a bound on *how many*: a leaked credential or a
runaway client could drive the write path as fast as the hub answers.

:class:`WriteQuota` keeps, per caller (the opaque key ``server._caller_key`` derives: an
OAuth subject, or a hash of the presented token, never the token), two sliding windows —
:data:`PER_MINUTE` writes in 60 s and :data:`PER_HOUR` in an hour — plus one hub-wide
window (:data:`GLOBAL_PER_MINUTE`) so many distinct credentials cannot add up to a flood.
A refused call is answered at once with the seconds until a slot frees, writes nothing,
and is audited by the tool's own refusal path. Only admitted calls count, and a call is
charged only after the caller's identity was accepted (a refused identity spends nobody's
budget). Callers are bucketed by what the hub can verify: when the write gate needs no
credential (the unset-token localhost posture) every caller shares one ``anonymous``
bucket, so rotating a header cannot mint fresh budgets; an owner-only tool
(``approval_respond``) is charged to one ``owner`` bucket. ``ask_<agent>`` (a full
orchestrator turn) has its own quota (:func:`shared_quota` ``"ask"``), keyed on a
verified OAuth subject, else ``anonymous``.

In memory, per process: a restart resets the windows (the audit trail does not).
"""

from __future__ import annotations

import threading
import time
from collections import deque

PER_MINUTE = 30
PER_HOUR = 300
GLOBAL_PER_MINUTE = 120
#: Callers tracked at once; the least recently seen is forgotten past this.
MAX_CALLERS = 1024


class WriteQuota:
    def __init__(self, *, per_minute: int = PER_MINUTE, per_hour: int = PER_HOUR,
                 global_per_minute: int = GLOBAL_PER_MINUTE, clock=time.monotonic) -> None:
        self.per_minute = int(per_minute)
        self.per_hour = int(per_hour)
        self.global_per_minute = int(global_per_minute)
        self._clock = clock
        self._lock = threading.Lock()
        self._callers: dict[str, deque[float]] = {}
        self._global: deque[float] = deque()

    @staticmethod
    def _trim(stamps: deque[float], horizon: float) -> None:
        while stamps and stamps[0] <= horizon:
            stamps.popleft()

    def admit(self, caller: str) -> float | None:
        """Admit one write for *caller*: None when admitted, else the seconds to wait."""
        now = self._clock()
        key = str(caller or "anonymous")
        with self._lock:
            self._trim(self._global, now - 60.0)
            stamps = self._callers.get(key)
            if stamps is None:
                stamps = deque()
            else:
                self._trim(stamps, now - 3600.0)
            last_minute = sum(1 for t in stamps if t > now - 60.0)
            waits = []
            if last_minute >= self.per_minute:
                waits.append(next(t for t in stamps if t > now - 60.0) + 60.0 - now)
            if len(stamps) >= self.per_hour:
                waits.append(stamps[0] + 3600.0 - now)
            if len(self._global) >= self.global_per_minute:
                waits.append(self._global[0] + 60.0 - now)
            if waits:
                if stamps:
                    self._callers[key] = stamps
                return max(0.1, max(waits))
            stamps.append(now)
            self._global.append(now)
            self._callers.pop(key, None)
            self._callers[key] = stamps              # most recently seen last
            while len(self._callers) > MAX_CALLERS:
                self._callers.pop(next(iter(self._callers)))
            return None

    def status(self) -> dict:
        now = self._clock()
        with self._lock:
            return {
                "per_minute": self.per_minute, "per_hour": self.per_hour,
                "global_per_minute": self.global_per_minute,
                "callers": len(self._callers),
                "global_last_minute": sum(1 for t in self._global if t > now - 60.0),
            }


# ── the hub's shared quotas (B1 of the H558 review) ─────────────────────────
#
# ``POST /api/mcp/server/rpc`` builds a fresh ``JarvisMCPServer`` for every request
# (``web._build_mcp_server``), and the stdio bridge forwards to that route, so a quota
# held by the server instance would start empty on every call. The hub passes these
# process-wide instances instead; a server built without one (tests, embedders) gets
# its own.

#: ``ask_<agent>`` runs a full orchestrator turn: limited apart from the writes so a
#: chatty client cannot use up the write budget (or the reverse).
ASK_PER_MINUTE = 20
ASK_PER_HOUR = 200
ASK_GLOBAL_PER_MINUTE = 60

_SHARED: dict[str, WriteQuota] = {}
_SHARED_LOCK = threading.Lock()


def shared_quota(kind: str = "write") -> WriteQuota:
    """The process-wide quota of *kind* (``write`` or ``ask``)."""
    with _SHARED_LOCK:
        quota = _SHARED.get(kind)
        if quota is None:
            if kind == "ask":
                quota = WriteQuota(per_minute=ASK_PER_MINUTE, per_hour=ASK_PER_HOUR,
                                   global_per_minute=ASK_GLOBAL_PER_MINUTE)
            else:
                quota = WriteQuota()
            _SHARED[kind] = quota
        return quota
