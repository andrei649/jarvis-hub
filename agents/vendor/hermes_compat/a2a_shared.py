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
import json as _json
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
    peer = _PEER.set("")            # each call starts with no peer named
    try:
        yield scope
    finally:
        _PEER.reset(peer)
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

#: One transcript or audit file grows to this, then is rotated to ``<name>.old`` (one kept).
MAX_FILE_BYTES = 256 * 1024
#: At most this many transcripts; a new one removes the oldest.
MAX_CONVERSATIONS = 200
_CONVERSATIONS_DIR = "a2a_conversations"

_PEER: contextvars.ContextVar[str] = contextvars.ContextVar("hermes_compat_a2a_peer", default="")


def note_peer(peer_id: str) -> None:
    """The Nerva request guard names the peer a request goes to (per call / fan-out task).
    Transcripts written afterwards in this context are filed under that peer, so one peer's
    ``contextId`` can never land in another peer's transcript."""
    _PEER.set(_safe_name(peer_id) or "peer")


def _safe_name(value: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in str(value or ""))[:64]


class _RedactingWriter:
    """An append handle that runs every JSON line's ``text``/``summary`` through redaction."""

    def __init__(self, fh: Any, redact: Callable[[str], str]) -> None:
        self._fh = fh
        self._redact = redact

    def write(self, data: str) -> int:
        out = []
        for line in str(data).splitlines(keepends=True):
            body = line.rstrip("\n")
            try:
                entry = _json.loads(body)
            except ValueError:
                entry = None
            if isinstance(entry, dict):
                for key in ("text", "summary"):
                    if isinstance(entry.get(key), str):
                        entry[key] = redact_for_egress(entry[key])
                body = _json.dumps(entry, ensure_ascii=False)
            else:
                body = redact_for_egress(body)
            out.append(body + ("\n" if line.endswith("\n") else ""))
        return self._fh.write("".join(out))

    def __enter__(self) -> _RedactingWriter:
        return self

    def __exit__(self, *exc: Any) -> None:
        self._fh.close()


class ConfinedPath:
    """The only path vendored code gets: under the scope's home, one plain name per step.

    ``/`` takes a single name (no separator, no ``..``); ``parent`` never leaves the home;
    ``open`` is append (redacted, size-rotated) or read; ``glob`` only ``*.jsonl``. A
    transcript name is prefixed with the peer the guard last named in this context."""

    __slots__ = ("_path", "_root")

    def __init__(self, root: _RealPath, path: _RealPath) -> None:
        self._root = root
        self._path = path

    def __truediv__(self, part: str) -> ConfinedPath:
        part = str(part)
        if (not part or part in {".", ".."} or "/" in part or "\\" in part or "\0" in part
                or part.startswith(".") or len(part) > 160):
            raise PermissionError("not a plain name")
        if self._path.name == _CONVERSATIONS_DIR and self._path.parent == self._root:
            peer = _PEER.get()
            if peer:
                part = f"{peer}__{part}"
        return ConfinedPath(self._root, self._path / part)

    @property
    def parent(self) -> ConfinedPath:
        if self._path == self._root:
            raise PermissionError("outside the A2A home")
        return ConfinedPath(self._root, self._path.parent)

    @property
    def name(self) -> str:
        return self._path.name

    @property
    def stem(self) -> str:
        return self._path.stem

    def exists(self) -> bool:
        return self._path.exists()

    def mkdir(self, parents: bool = False, exist_ok: bool = False) -> None:
        self._path.mkdir(parents=True, exist_ok=True)

    def read_text(self, encoding: str = "utf-8", errors: str | None = None) -> str:
        return self._path.read_text(encoding=encoding, errors=errors)

    def glob(self, pattern: str) -> list[ConfinedPath]:
        if pattern != "*.jsonl":
            raise PermissionError("unsupported pattern")
        if not self._path.is_dir():
            return []
        return [ConfinedPath(self._root, p) for p in sorted(self._path.glob("*.jsonl"))
                if p.is_file() and not p.is_symlink()]

    def open(self, mode: str = "r", encoding: str | None = "utf-8", **_ignored: Any) -> Any:
        if self._path.is_symlink():
            raise PermissionError("symlink")
        if mode == "r":
            return self._path.open("r", encoding=encoding)
        if mode != "a":
            raise PermissionError("append or read only")
        self._rotate()
        scope = _SCOPE.get()
        if scope is None or scope.redact is None:
            raise PermissionError("no redaction bound")
        return _RedactingWriter(self._path.open("a", encoding=encoding or "utf-8"), scope.redact)

    def _rotate(self) -> None:
        path = self._path
        if path.exists() and path.stat().st_size > MAX_FILE_BYTES:
            path.replace(path.with_name(path.name + ".old"))
        folder = path.parent
        if folder.name == _CONVERSATIONS_DIR and not path.exists() and folder.is_dir():
            files = sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
            for old in files[:max(0, len(files) - MAX_CONVERSATIONS + 1)]:
                old.unlink(missing_ok=True)
                old.with_name(old.name + ".old").unlink(missing_ok=True)

    def __fspath__(self) -> str:
        raise PermissionError("vendored code gets no raw path")


def get_hermes_home() -> ConfinedPath:
    scope = _SCOPE.get()
    if scope is None or scope.home is None:
        raise PermissionError("no Nerva A2A scope is bound")
    return ConfinedPath(scope.home, scope.home)


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
    "A2AScope", "ConfinedPath", "MAX_CONVERSATIONS", "MAX_FILE_BYTES", "Path",
    "REDACTION_UNAVAILABLE", "bound_scope", "note_peer", "coerce_port", "current_scope",
    "get_hermes_home", "get_scoped_secret", "get_secret", "is_loopback_host", "load_config",
    "load_config_readonly", "profile_scoped", "redact_for_egress",
]
