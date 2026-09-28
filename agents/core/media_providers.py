"""Shared provider identity and immutable lookup; registration grants no authority.

Only explicitly constructed trusted adapters enter a registry. User configuration
may select their data, never an import path. Domain adapters own the guarded I/O;
catalog construction and lookup never call availability, setup or execution hooks.
"""
from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path
from types import MappingProxyType

PROVIDER_KINDS = frozenset({"image", "video", "tts", "stt", "browser", "web", "terminal"})
_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}")
_SOURCE = Path(__file__)
_IMPORTED_SHA = hashlib.sha256(_SOURCE.read_bytes()).hexdigest()


class ProviderBase(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Stable configuration identity within one provider kind."""

    @property
    @abstractmethod
    def kind(self) -> str:
        """Domain whose guarded dispatcher consumes this adapter."""

    @property
    def display_name(self) -> str:
        return self.name

    def get_setup_schema(self) -> dict | None:
        """Pure picker metadata; None hides an adapter from setup controls."""
        return {"name": self.display_name, "badge": "", "tag": "", "env_vars": []}

    def is_available(self) -> bool:
        """Cheap configuration check, never a live probe or permission grant."""
        return False


class ProviderRegistry[P: ProviderBase]:
    """A fresh, immutable mapping with no replacement or implicit discovery."""

    def __init__(self, providers: Iterable[P] = ()):
        records = {}
        for provider in providers:
            if not isinstance(provider, ProviderBase):
                raise TypeError("expected ProviderBase")
            name, kind = provider.name, provider.kind
            if (not isinstance(name, str) or not _NAME.fullmatch(name)
                    or not isinstance(kind, str) or kind not in PROVIDER_KINDS):
                raise ValueError("invalid provider identity")
            key = (kind, name)
            if key in records:
                raise ValueError("duplicate provider identity")
            records[key] = provider
        self._records = MappingProxyType(records)

    def get(self, kind: str, name: str) -> P | None:
        if not isinstance(kind, str) or not isinstance(name, str):
            return None
        return self._records.get((kind, name))

    def list(self, kind: str | None = None) -> tuple[P, ...]:
        return tuple(provider for (domain, _), provider in self._records.items()
                     if kind is None or domain == kind)


def registry_source_fingerprint() -> str:
    """Keep image approval bindings sensitive to shared lookup implementation drift."""
    try:
        if hashlib.sha256(_SOURCE.read_bytes()).hexdigest() != _IMPORTED_SHA:
            raise ValueError("provider_registry_source_changed")
    except OSError:
        raise ValueError("provider_registry_source_changed") from None
    return _IMPORTED_SHA
