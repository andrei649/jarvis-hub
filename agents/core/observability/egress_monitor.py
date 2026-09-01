"""egress_monitor.py — H23.16 network monitor: record every outbound attempt.

The plugin egress choke point (`core/http_client.py`) calls :func:`record` for every
HTTP request — *allowed and blocked alike* — so we have a single, truthful ledger of
what actually left (or tried to leave) the machine, per plugin and per host. The HUD
network panel reads :func:`snapshot` to **prove** that LOCAL_ONLY / no-network plugins
make zero outbound calls (and to surface any blocked attempt), which is the whole point
of the local-first kernel mediation story.

DRA-23: the ledger covers **model-backend egress** too. `core/llm/egress.py` records
every LLM request under an ``llm:<provider>`` row, so a turn served by a cloud model
shows up here instead of leaving invisibly; ``model_egress_total`` is that traffic's
share of ``external_egress_total``. Those rows have no plugin manifest, so
:meth:`_local_only_violations` skips them — a cloud call is honest egress, not a breach.

Design mirrors ``http_metrics.py``: a single in-process, thread-safe instance, no
external dependency. State is **in-memory** — monotonic per-plugin counters plus a
bounded ring buffer of recent events — so it resets on restart (this is live
observability, not a forensic audit log; the security audit log is the durable record).
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import UTC, datetime

# Recent-event ring buffer size. Bounded so a busy plugin can't grow memory without
# limit; the monotonic counters below keep exact totals regardless of eviction.
_MAX_EVENTS = 1000


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class _PluginStat:
    """Monotonic per-plugin tallies (survive ring-buffer eviction)."""

    __slots__ = ("total", "allowed", "blocked", "external", "last_ts", "last_host")

    def __init__(self) -> None:
        self.total = 0
        self.allowed = 0
        self.blocked = 0
        self.external = 0  # allowed calls to a non-local host
        self.last_ts: str | None = None
        self.last_host: str | None = None


class EgressMonitor:
    """In-process ledger of plugin HTTP egress attempts.

    One module-level instance (:data:`EGRESS_MONITOR`) is shared by the egress choke
    point (writer) and the admin endpoint (reader); a single lock guards both so the
    snapshot is consistent while requests record concurrently.
    """

    def __init__(self, max_events: int = _MAX_EVENTS) -> None:
        self._lock = threading.Lock()
        self._events: deque[dict] = deque(maxlen=max_events)
        self._stats: dict[str, _PluginStat] = {}

    def record(
        self,
        plugin: str,
        host: str,
        method: str,
        *,
        allowed: bool,
        local: bool,
        reason: str = "",
    ) -> None:
        """Record one outbound attempt. Never raises — observability must not break egress."""
        ts = _now_iso()
        event = {
            "ts": ts,
            "plugin": plugin or "unknown",
            "host": host or "",
            "method": (method or "GET").upper(),
            "allowed": bool(allowed),
            "local": bool(local),
            "reason": reason or "",
        }
        with self._lock:
            self._events.append(event)
            st = self._stats.get(event["plugin"])
            if st is None:
                st = self._stats[event["plugin"]] = _PluginStat()
            st.total += 1
            st.last_ts = ts
            st.last_host = event["host"]
            if allowed:
                st.allowed += 1
                if not local:
                    st.external += 1
            else:
                st.blocked += 1

    def snapshot(self, plugin: str | None = None, limit: int = 100) -> dict:
        """Return per-plugin summary + recent events, optionally filtered to one plugin.

        ``recent`` is newest-first and capped at *limit*. ``external_egress_total`` is the
        count of allowed calls that left the machine, of which ``model_egress_total`` is
        the ``llm:``-prefixed (model-backend) share; ``local_only_violations`` lists the
        plugins that *did* make an external call despite a local-only manifest (should
        always be empty — the gate blocks them — which is exactly what we want to show).
        """
        limit = max(0, min(int(limit or 0), _MAX_EVENTS))
        with self._lock:
            items = [e for e in self._events if plugin is None or e["plugin"] == plugin]
            recent = list(reversed(items))[:limit]
            plugins = {
                name: {
                    "total": st.total,
                    "allowed": st.allowed,
                    "blocked": st.blocked,
                    "external": st.external,
                    "last_ts": st.last_ts,
                    "last_host": st.last_host,
                }
                for name, st in sorted(self._stats.items())
                if plugin is None or name == plugin
            }
        external_total = sum(p["external"] for p in plugins.values())
        # DRA-23: the model-backend share of the external total, so a surface can say
        # "local-first" about plugin traffic without implying it about the models.
        model_total = sum(
            p["external"] for name, p in plugins.items() if name.startswith("llm:")
        )
        violations = self._local_only_violations(plugins)
        return {
            "plugins": plugins,
            "recent": recent,
            "external_egress_total": external_total,
            "model_egress_total": model_total,
            "local_only_violations": violations,
            "clean": not violations,
            "events_kept": len(recent),
        }

    @staticmethod
    def _local_only_violations(plugins: dict) -> list[str]:
        """Plugins that made an allowed external call despite a local-only manifest.

        Cross-checks recorded egress against the declared network policy — the proof
        that the kernel's mediation held. Best-effort: if the manifest registry can't be
        imported, we can't classify, so we report none rather than guess.
        """
        try:
            from agents.core.plugin_gate import BUILTIN_PLUGINS, NetworkAccess
        except Exception:
            return []
        out = []
        for name, p in plugins.items():
            if p["external"] <= 0:
                continue
            manifest = BUILTIN_PLUGINS.get(name)
            if manifest is not None and manifest.network_access in (
                NetworkAccess.NONE,
                NetworkAccess.LAN,
            ):
                out.append(name)
        return out

    def reset(self) -> None:
        """Clear all state (used by tests for isolation)."""
        with self._lock:
            self._events.clear()
            self._stats.clear()


# Module-level singleton shared by the choke point and the admin endpoint.
EGRESS_MONITOR = EgressMonitor()
