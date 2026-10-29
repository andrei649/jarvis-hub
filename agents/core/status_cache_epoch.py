"""Bounded process-local cache ratios for authenticated conversation instances.

Only numeric disjoint prompt counters and trusted session/route identities live here.
The map is capped and never stores prompts, result payloads or provider credentials.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass

_MAX_TOKENS = 1_000_000_000_000


@dataclass(slots=True)
class _Counts:
    uncached: int = 0
    read: int = 0
    write: int = 0
    unknown: bool = False


class CacheEpochs:
    def __init__(self, max_scopes: int = 64) -> None:
        self._lock = threading.RLock()
        self._max_scopes = max(1, min(max_scopes, 256))
        self._entries: OrderedDict[tuple, _Counts] = OrderedDict()
        self._poisoned: OrderedDict[tuple, bool] = OrderedDict()
        self._overflowed = False

    def _entry(self, key: tuple) -> _Counts:
        entry = self._entries.get(key)
        if entry is None:
            # A verified physical route/model transition invalidates this agent's
            # prompt prefix even if selection happened outside a settings writer.
            for prior in tuple(self._entries):
                if prior[:4] == key[:4] and prior[4:] != key[4:]:
                    del self._entries[prior]
            if len(self._entries) >= self._max_scopes:
                self._entries.popitem(last=False)
                self._overflowed = True
            entry = _Counts()
            if key[:3] in self._poisoned:
                entry.unknown = True
            self._entries[key] = entry
        self._entries.move_to_end(key)
        return entry

    def observe(self, key: tuple, uncached: int, read: int, write: int) -> float | None:
        with self._lock:
            item = self._entry(key)
            fields = (uncached, read, write)
            if (any(type(value) is not int or not 0 <= value <= _MAX_TOKENS for value in fields)
                    or sum(fields) > _MAX_TOKENS):
                item.unknown = True
            elif not item.unknown:
                item.uncached += uncached
                item.read += read
                item.write += write
                if item.uncached + item.read + item.write > _MAX_TOKENS:
                    item.unknown = True
            return None if self._overflowed else self._value(item)

    def contaminate(self, key: tuple) -> None:
        with self._lock:
            self._entry(key).unknown = True

    def contaminate_conversation(self, conversation: tuple) -> None:
        with self._lock:
            if conversation not in self._poisoned and len(self._poisoned) >= self._max_scopes:
                self._poisoned.popitem(last=False)
                self._overflowed = True
            self._poisoned[conversation] = True
            self._poisoned.move_to_end(conversation)
            for key, item in self._entries.items():
                if key[:3] == conversation:
                    item.unknown = True

    @staticmethod
    def _value(item: _Counts | None) -> float | None:
        if item is None or item.unknown or item.read == 0:
            return None
        total = item.uncached + item.read + item.write
        return 100 * item.read / total if total > 0 else None

    def value(self, key: tuple) -> float | None:
        with self._lock:
            return None if self._overflowed else self._value(self._entries.get(key))

    def invalidate_conversation(self, conversation: tuple) -> None:
        with self._lock:
            self._poisoned.pop(conversation, None)
            for key in tuple(self._entries):
                if key[:3] == conversation:
                    del self._entries[key]

    def invalidate_instance(self, session_id: str, instance_id: str) -> None:
        """A durable compaction changed this chat prefix for every principal."""
        with self._lock:
            for conversation in tuple(self._poisoned):
                if conversation[1:3] == (session_id, instance_id):
                    del self._poisoned[conversation]
            for key in tuple(self._entries):
                if key[1:3] == (session_id, instance_id):
                    del self._entries[key]

    def invalidate_selection(self) -> None:
        with self._lock:
            self._entries.clear()
            self._poisoned.clear()
            self._overflowed = False


EPOCHS = CacheEpochs()
