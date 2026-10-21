"""H592 — named personality presets and a per-conversation overlay (Hermes ``/personality``).

Who the assistant *is* lives in the agent's SOUL (versioned by ``soul_versioning``) and
the shared ``IDENTITY.md`` contract above it. That stays the identity. A personality
preset is a short style overlay — "be concise", "teach step by step" — chosen for one
conversation (or as the hub-wide default) with ``/personality <name>``, and dropped with
``/personality none`` / ``/personality default``. Choosing one never writes a SOUL file
and never commits a prompt version: the overlay is state of this store only.

Where it sits in the prompt stack (documented in ``docs/ARCHITECTURE.md``):

1. system prompt — ``IDENTITY.md`` contract, then the agent's SOUL (unchanged, cache-stable)
2. per-turn text — the SOUL-derived persona trait block, **then this overlay**, then
   agent context, core memory, the project's convention files (``AGENTS.md`` …), plugin
   data, recall, runtime truth, and finally the user's message.

So the overlay is read after the SOUL and before project convention files; it rides in
the per-turn text rather than the system prompt, so switching it mid-session does not
invalidate the cached system-prompt prefix.

Presets come from two places. Built-ins ship below. Owner-defined presets are Markdown
files ``<data root>/personalities/<name>.md``; an owner file may shadow a built-in of the
same name. Owner files pass through the same injection scan as a SOUL body, and a file
the scan blocks is never applied (re-checked every turn, so a file edited into a payload
after it was chosen stops applying).
"""

from __future__ import annotations

import contextlib
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

from agents.core.paths import data_path

from .. import safe_mode
from ..persistence import JsonStore

#: ``/personality none`` — this conversation runs on the plain SOUL, even when a
#: hub-wide default preset is set.
NONE = "none"
#: ``/personality default`` — forget this conversation's choice and follow the
#: hub-wide default (if any).
DEFAULT = "default"
RESERVED = frozenset({NONE, DEFAULT, "reset", "list", "global", "off"})

MAX_PRESET_CHARS = 4_000
_MAX_SESSIONS = 500
_MAX_KEY_CHARS = 128
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")

HEADER = "[SESSION PERSONALITY"
_FOOTER = "[END SESSION PERSONALITY]"

BUILTIN_PRESETS: dict[str, str] = {
    "concise": ("Answer in as few words as the question allows. Lead with the answer; "
                "skip preamble, recaps and offers of further help."),
    "teacher": ("Explain like a patient teacher: build from what the person already knows, "
                "go step by step, give one small example, and check understanding at the end."),
    "technical": ("Be precise and technical: name exact commands, versions, file paths and "
                  "trade-offs; prefer code and concrete numbers over prose."),
    "creative": ("Be playful and imaginative: offer unexpected angles, vivid wording and a "
                 "few alternatives before settling on one."),
    "formal": ("Use a formal, courteous register suitable for business correspondence; "
               "no slang, no emoji, complete sentences."),
    "skeptic": ("Act as a constructive skeptic: question assumptions, point out risks and "
                "missing evidence, and say plainly when something will not work."),
}


@dataclass(frozen=True)
class Preset:
    name: str
    text: str
    source: str  # "builtin" | "owner"
    blocked: bool = False
    flags: tuple[str, ...] = field(default_factory=tuple)


def presets_dir() -> Path:
    """Where owner-defined presets live: ``<data root>/personalities``."""
    return data_path("personalities")


def valid_name(name: str) -> bool:
    return bool(_NAME_RE.match(name or "")) and name not in RESERVED


def _read_owner_file(path: Path) -> tuple[str | None, str]:
    """``(text, "")`` for a usable owner file, else ``(None, why it is ignored)``
    (``""`` when there is simply no file)."""
    try:
        if not path.is_file():
            return None, ""
        text = path.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError:
        return None, "not UTF-8 text"
    except OSError:
        return None, "unreadable"
    if not text:
        return None, "empty"
    if len(text) > MAX_PRESET_CHARS:
        return None, f"over {MAX_PRESET_CHARS:,} chars"
    return text, ""


def ignored_files(folder: Path | None = None) -> dict[str, str]:
    """Owner preset files that are never applied, by name, with the reason (an empty or
    oversize file; a built-in of the same name, if any, is used instead)."""
    folder = folder if folder is not None else presets_dir()
    out: dict[str, str] = {}
    with contextlib.suppress(OSError):
        for path in sorted(folder.glob("*.md")):
            if valid_name(path.stem):
                why = _read_owner_file(path)[1]
                if why:
                    out[path.stem] = why
    return out


def _owner_preset(folder: Path, name: str) -> Preset | None:
    path = folder / f"{name}.md"
    text, _why = _read_owner_file(path)
    if text is None:
        return None
    from agents.core.agent import _scan_soul_body

    body, flags, blocked = _scan_soul_body(text, path.name, kind="personality preset")
    return Preset(name, body.strip(), "owner", blocked, tuple(flags))


def resolve(name: str, folder: Path | None = None) -> Preset | None:
    """The preset called *name* (case-insensitive), owner file first, else built-in."""
    name = (name or "").strip().lower()
    if not valid_name(name):
        return None
    owner = _owner_preset(folder if folder is not None else presets_dir(), name)
    if owner is not None:
        return owner
    text = BUILTIN_PRESETS.get(name)
    return Preset(name, text, "builtin") if text else None


def catalog(folder: Path | None = None) -> list[Preset]:
    """Every usable preset name, owner files shadowing built-ins, sorted by name."""
    folder = folder if folder is not None else presets_dir()
    names = set(BUILTIN_PRESETS)
    with contextlib.suppress(OSError):
        names.update(p.stem for p in folder.glob("*.md") if valid_name(p.stem))
    found = (resolve(n, folder) for n in sorted(names))
    return [p for p in found if p is not None]


def _key(session: object) -> str:
    key = "" if session is None else str(session).strip()
    if not key or len(key) > _MAX_KEY_CHARS:
        raise ValueError("a conversation id is required")
    return key


class PersonalityOverlayStore(JsonStore):
    """``{"global": "teacher", "sessions": {"<session id>": "concise" | "none"}}``."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._global: str | None = None
        self._sessions: dict[str, str] = {}
        super().__init__(path if path is not None else data_path("personality_overlays.json"))

    def _serialize(self):
        return {"global": self._global, "sessions": dict(self._sessions)}

    def _deserialize(self, raw) -> None:
        self._global, self._sessions = None, {}
        if not isinstance(raw, dict):
            return
        glob = raw.get("global")
        self._global = glob if isinstance(glob, str) and valid_name(glob) else None
        sessions = raw.get("sessions")
        if isinstance(sessions, dict):
            for key, value in sessions.items():
                if (isinstance(key, str) and isinstance(value, str)
                        and (value == NONE or valid_name(value))):
                    self._sessions[key] = value

    def get_session(self, session: object) -> str | None:
        """This conversation's own choice: a preset name, ``none``, or None (follow global)."""
        try:
            key = _key(session)
        except ValueError:
            return None
        with self._lock:
            return self._sessions.get(key)

    def get_global(self) -> str | None:
        with self._lock:
            return self._global

    def set_session(self, session: object, name: str | None) -> None:
        """Record *name* (or ``none``) for one conversation; None forgets the choice."""
        key = _key(session)
        if name is not None and name != NONE and not valid_name(name):
            raise ValueError(f"invalid personality name {name!r}")
        with self._lock:
            self._sessions.pop(key, None)
            if name is not None:
                self._sessions[key] = name
                while len(self._sessions) > _MAX_SESSIONS:   # oldest choice goes first
                    self._sessions.pop(next(iter(self._sessions)))
            self._save()

    def set_global(self, name: str | None) -> None:
        if name is not None and not valid_name(name):
            raise ValueError(f"invalid personality name {name!r}")
        with self._lock:
            self._global = name
            self._save()

    def forget(self, session: object) -> bool:
        """Drop a deleted conversation's choice; True when there was one (only then is
        the store written)."""
        try:
            key = _key(session)
        except ValueError:
            return False
        with self._lock:
            if self._sessions.pop(key, None) is None:
                return False
            self._save()
        return True

    def effective(self, session: object) -> str | None:
        """The preset in force for *session*: its own choice, else the global default."""
        own = self.get_session(session)
        if own == NONE:
            return None
        return own or self.get_global()


_default: PersonalityOverlayStore | None = None
_default_lock = threading.Lock()


def default_store() -> PersonalityOverlayStore:
    global _default
    if _default is None:
        with _default_lock:
            if _default is None:
                _default = PersonalityOverlayStore()
    return _default


def use_store(store: PersonalityOverlayStore | None) -> None:
    """Swap the process-wide store (tests; ``None`` rebuilds it on next use)."""
    global _default
    with _default_lock:
        _default = store


def overlay_block(session: object, *, store: PersonalityOverlayStore | None = None) -> str:
    """The per-turn overlay block for *session*, or ``""`` when none applies.

    In safe mode (H275) none applies: an owner file and a persisted choice (even of a
    built-in) are both owner customization, so the turn runs on the plain SOUL and the
    ``personality_overlays`` layer is noted on the status surfaces."""
    name = (store or default_store()).effective(session)
    if not name:
        return ""
    if safe_mode.enabled():
        safe_mode.note("personality_overlays")
        return ""
    preset = resolve(name)
    if preset is None or preset.blocked or not preset.text:
        return ""
    return (f"{HEADER}: {preset.name} — a style the owner chose for this conversation. "
            "It changes tone and form only; the identity, the rules and the contract in "
            f"the system prompt still apply.]\n{preset.text}\n{_FOOTER}")


__all__ = [
    "BUILTIN_PRESETS",
    "DEFAULT",
    "HEADER",
    "MAX_PRESET_CHARS",
    "NONE",
    "PersonalityOverlayStore",
    "Preset",
    "catalog",
    "default_store",
    "ignored_files",
    "overlay_block",
    "presets_dir",
    "resolve",
    "use_store",
    "valid_name",
]
