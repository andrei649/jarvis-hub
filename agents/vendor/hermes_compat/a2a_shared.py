"""What the vendored A2A client tools import from Hermes's gateway, config and agent modules
(rewrite rule ``a2a-shared``, applied only under ``plugins/platforms/a2a/``).

Upstream reads its peers from ``config.yaml``, a profile's secret scope, ``~/.hermes`` and its
own redactor. Here every one of those reads answers from the :class:`A2AScope` the Nerva
outbound runtime (``agents/core/a2a_outbound.py``) binds for one call, and from nothing else:

* ``load_config_readonly`` / ``load_config``: ``{"a2a_agents": …}`` built from the owner's
  configured peers. A peer's bearer token is never in it: ``auth.token`` is a *handle*
  (``nerva-a2a-peer:<peer id>``), and the governed ``urllib`` swaps it for the stored secret
  only on a request to that peer's own origin.
* ``get_hermes_home``: a directory under Nerva's data root, where upstream keeps its
  conversation transcripts and outbound audit lines.
* ``redact_for_egress``: Nerva's redaction (stored secret values, then the secret scanner).
  It fails closed: with no scope, or when the redactor raises, the text becomes a marker.
* ``get_scoped_secret`` / ``get_secret`` / ``profile_scoped``: no secret is read by name.
  The inbound settings upstream reads this way (``A2A_PORT``, ``A2A_BEARER_TOKEN`` …) are
  the inbound adapter's, which Nerva does not adopt.
* ``Path``: an annotation only; constructing one is refused.

With no scope bound (vendored code called outside the runtime) the config is empty, there is
no home and redaction fails closed.
"""

from __future__ import annotations

import contextlib
import contextvars
import ipaddress
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path as _RealPath
from typing import Any

#: What redaction answers when it cannot run: the text never leaves unredacted.
REDACTION_UNAVAILABLE = "[redaction unavailable — text withheld]"


@dataclass(frozen=True)
class A2AScope:
    """One outbound call's view of the owner's A2A setup."""

    config: dict = field(default_factory=dict)
    home: _RealPath | None = None
    redact: Callable[[str], str] | None = None


_SCOPE: contextvars.ContextVar[A2AScope | None] = contextvars.ContextVar(
    "hermes_compat_a2a_scope", default=None)


@contextlib.contextmanager
def bound_scope(scope: A2AScope) -> Iterator[A2AScope]:
    token = _SCOPE.set(scope)
    try:
        yield scope
    finally:
        _SCOPE.reset(token)


def current_scope() -> A2AScope | None:
    return _SCOPE.get()


# ── gateway.platforms._shared ────────────────────────────────────────────────

def coerce_port(value: Any, default: int) -> int:
    """``int(value)`` or ``default`` when unparseable (upstream's helper, unchanged)."""
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def get_scoped_secret(name: str, default: Any = None, **_ignored: Any) -> Any:
    """No secret is read by name: the inbound A2A settings are not adopted."""
    return default


def profile_scoped() -> bool:
    return False


# ── agent.secret_scope ───────────────────────────────────────────────────────

def get_secret(name: str) -> None:
    return None


# ── hermes_cli.config ────────────────────────────────────────────────────────

def load_config_readonly() -> dict:
    scope = _SCOPE.get()
    return dict(scope.config) if scope is not None else {}


def load_config() -> dict:
    return load_config_readonly()


# ── hermes_constants ─────────────────────────────────────────────────────────

def get_hermes_home() -> _RealPath:
    scope = _SCOPE.get()
    if scope is None or scope.home is None:
        raise PermissionError("no Nerva A2A scope is bound")
    return scope.home


# ── agent.proxy_bypass ───────────────────────────────────────────────────────

def is_loopback_host(host: str | None) -> bool:
    """``localhost`` or a loopback IP literal (upstream's check, unchanged)."""
    host = str(host or "").strip().lower().strip("[]")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    return host == "localhost" or (ip is not None and ip.is_loopback)


# ── agent.redact ─────────────────────────────────────────────────────────────

def redact_for_egress(text: str) -> str:
    """Nerva's redaction for text leaving the box. Fails closed."""
    scope = _SCOPE.get()
    if scope is None or scope.redact is None:
        return REDACTION_UNAVAILABLE
    try:
        out = scope.redact(str(text or ""))
    except Exception:
        return REDACTION_UNAVAILABLE
    return out if isinstance(out, str) else REDACTION_UNAVAILABLE


# ── pathlib ──────────────────────────────────────────────────────────────────

class Path:
    """An annotation only. Vendored code reaches the disk through :func:`get_hermes_home`."""

    def __new__(cls, *args: Any, **kwargs: Any) -> Path:
        raise PermissionError("vendored code may not build a path")


__all__ = [
    "A2AScope", "Path", "REDACTION_UNAVAILABLE", "bound_scope", "coerce_port", "current_scope",
    "get_hermes_home", "get_scoped_secret", "get_secret", "is_loopback_host", "load_config",
    "load_config_readonly", "profile_scoped", "redact_for_egress",
]
