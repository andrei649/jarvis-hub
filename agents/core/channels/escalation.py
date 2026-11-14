"""Pure, bounded health episodes for channel failure notices.

The manager owns the clocked sampling and delivery. This tracker only decides
whether an episode has earned its one notice; a True result spends that notice
before the caller can queue it. It never starts a retry or sends a message.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from time import monotonic

MONITOR_INTERVAL = 10.0
FAILURE_AFTER = 300.0
HEALTHY_AFTER = 60.0


@dataclass(slots=True)
class _Episode:
    adapter: object
    revision: int
    failed_since: float | None = None
    healthy_since: float | None = None
    spent: bool = False

    def clear_intervals(self) -> None:
        self.failed_since = None
        self.healthy_since = None

    def spend(self) -> bool:
        self.clear_intervals()
        if self.spent:
            return False
        self.spent = True
        return True


class FailureEscalation:
    """One episode per registered channel identity, on a monotonic clock.

    The manager must admit only its current registered adapter before calling
    :meth:`fatal`, since a callback may arrive before the first sampled row.
    :meth:`observe` replaces a row for a new exact adapter/revision, while an old
    fatal callback never replaces an existing newer row. `prune` or `retire`
    discards rows for registrations that no longer exist.
    """

    def __init__(self, *, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._episodes: dict[str, _Episode] = {}

    def observe(self, cid: str, adapter: object, revision: int,
                snapshot: object, eligible: bool) -> bool:
        """Return True once for a current confirmed failure or fatal episode.

        Unknown and initial-not-ready observations interrupt pending durations.
        A healthy sample interrupts failure immediately but must remain healthy
        for `HEALTHY_AFTER` before another notice can be earned.
        """
        episode = self._episodes.get(cid)
        if episode is None or episode.adapter is not adapter or episode.revision != revision:
            episode = _Episode(adapter, revision)
            self._episodes[cid] = episode
        if not eligible or type(snapshot) is not dict:
            episode.clear_intervals()
            return False

        state = snapshot.get("state")
        if state == "fatal":
            return episode.spend()

        now = self._clock()
        if state == "healthy":
            episode.failed_since = None
            if episode.healthy_since is None or now < episode.healthy_since:
                episode.healthy_since = now
            elif now - episode.healthy_since >= HEALTHY_AFTER:
                episode.spent = False
            return False

        episode.healthy_since = None
        if (state != "retrying" or type(snapshot.get("failures")) is not int
                or snapshot["failures"] <= 0):
            episode.failed_since = None
            return False
        if episode.failed_since is None or now < episode.failed_since:
            episode.failed_since = now
            return False
        if now - episode.failed_since < FAILURE_AFTER:
            return False
        return episode.spend()

    def fatal(self, cid: str, adapter: object, revision: int) -> bool:
        """Spend the same episode for a native fatal callback, immediately."""
        episode = self._episodes.get(cid)
        if episode is None:
            episode = _Episode(adapter, revision)
            self._episodes[cid] = episode
        elif episode.adapter is not adapter or episode.revision != revision:
            return False
        return episode.spend()

    def retire(self, cid: str) -> None:
        """Forget one registration when the manager replaces or removes it."""
        self._episodes.pop(cid, None)

    def reset(self) -> None:
        """Forget every episode when the manager lifecycle stops."""
        self._episodes.clear()

    def prune(self, current_keys: Mapping[str, tuple[object, int]]) -> None:
        """Keep only exact live adapter/revision pairs from the registry."""
        for cid, episode in tuple(self._episodes.items()):
            current = current_keys.get(cid)
            if (current is None or type(current) is not tuple or len(current) != 2
                    or current[0] is not episode.adapter or current[1] != episode.revision):
                del self._episodes[cid]


__all__ = ["MONITOR_INTERVAL", "FAILURE_AFTER", "HEALTHY_AFTER", "FailureEscalation"]
