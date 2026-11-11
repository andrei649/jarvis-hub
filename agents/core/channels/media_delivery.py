"""media_delivery.py — which local files may leave in a chat reply, and how (H070, G16).

A reply can name a file the turn produced with a line of its own::

    MEDIA: /path/to/the/file.png

The line is taken out of the words and the file is attached after them. Which files may
leave is an exfiltration policy, not a convenience, so every rule here refuses by default:

* **Approved output directories only.** A file is deliverable only when it lies under one
  of the delivery roots: the hub's own output folders (``<data>/outputs``,
  ``<data>/media/generated``, ``<data>/reports``) that exist, plus any directory the owner
  lists in ``JARVIS_MEDIA_DELIVERY_DIRS`` (``os.pathsep``-separated, absolute, existing).
  A listed directory that is, or contains, a protected place (the filesystem root, the
  home directory, the data root, its ``security``/``tokens``/``vault`` folders, the code
  checkout) or lies inside a private home folder (``~/.ssh``, ``~/.gnupg``, ``~/.config`` …)
  is ignored and named in the log; it can never widen the policy that far.
* **No escape.** The path must be absolute. ``..`` is refused before anything is
  resolved, the fully resolved path must still be under a resolved root (a symlink inside
  a root that points out of it is refused), the final component may not be a symlink at
  all. The file is then opened one component at a time from the root, each with
  ``O_NOFOLLOW`` relative to the folder opened before it, so a folder swapped for a link
  between the check and the open fails the walk; the opened file must be the very file
  that was checked (inode and device), and a file with more than one name (a hard link,
  which could carry a protected file into an approved folder) is refused.
* **Never secrets, config or data stores.** A hidden component (``.ssh``, ``.env``), a
  name that looks like a credential or a key (``*.pem``, ``*.key``, ``id_rsa``,
  ``secrets*``, ``credentials*``, ``*token*``), a database or settings file (``*.db``,
  ``*.sqlite``, ``*.enc``, ``*.json`` config in a protected tree) or anything under the
  protected folders above is refused even inside an approved root.
* **Regular files of bounded size.** The path must be a regular file before anything is
  opened (a FIFO or device would block), and it is opened non-blocking and checked again;
  the adapter also bounds the whole check in time. ``JARVIS_MEDIA_DELIVERY_MAX_BYTES``
  (20 MiB by default, never above 50 MiB — Telegram's bot upload limit); an empty file is
  refused.
* **Directives.** Only a ``MEDIA:`` line of its own, outside a fenced code block, counts;
  while a reply streams, those lines are held back (:func:`strip_partial`).
* **At most** :data:`MAX_FILES_PER_REPLY` files per reply.

A refusal is a short reason (``outside_allowed_dirs``, ``symlink``, ``too_large`` …) that
the chat is told as one line; the path itself is never echoed back into the chat or the
log. Who may receive a file, and the kernel crossing, are the adapter's call
(``telegram.py``: only the owner, inside the turn that produced it).
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from ..env_config import env_int, env_str

logger = logging.getLogger("jarvis.channels.media_delivery")

DIRS_ENV = "JARVIS_MEDIA_DELIVERY_DIRS"
MAX_BYTES_ENV = "JARVIS_MEDIA_DELIVERY_MAX_BYTES"
DEFAULT_MAX_BYTES = 20 * 1024 * 1024
MAX_BYTES_CEILING = 50 * 1024 * 1024
MAX_FILES_PER_REPLY = 4
#: A directive line: ``MEDIA:`` then a path, alone on its line (leading spaces allowed).
_DIRECTIVE = re.compile(r"^[ \t]*MEDIA:[ \t]*(?P<path>\S[^\r\n]*?)[ \t]*$", re.MULTILINE)
_MAX_PATH = 1024

#: Names that are never sent, wherever they are (lower-cased match on the file name).
_SECRET_NAME = re.compile(
    r"(^id_(rsa|dsa|ecdsa|ed25519)|\.(pem|key|p12|pfx|kdbx|enc|db|sqlite3?|db-wal|db-shm|"
    r"keystore|jks|gpg|asc)$|^(secrets?|credentials?|\.?env)([._-]|$)|token|passw|"
    r"private[_-]?key|\.netrc$|authorized_keys|known_hosts)")

REASON_NOT_ABSOLUTE = "not_absolute"
REASON_TRAVERSAL = "path_traversal"
REASON_OUTSIDE = "outside_allowed_dirs"
REASON_SYMLINK = "symlink"
REASON_PROTECTED = "protected_location"
REASON_SECRET_NAME = "secret_like_name"  # nosec B105 — a refusal reason, not a credential
REASON_NOT_FILE = "not_a_regular_file"
REASON_MISSING = "not_found"
REASON_TOO_LARGE = "too_large"
REASON_EMPTY = "empty"
REASON_UNREADABLE = "unreadable"
REASON_TOO_MANY = "too_many_files"
REASON_HARDLINK = "hard_link"
REASON_TIMEOUT = "timed_out"

#: What the chat is told for each refusal (never the path).
REFUSAL_TEXT = {
    REASON_NOT_ABSOLUTE: "the path is not absolute",
    REASON_TRAVERSAL: "the path climbs out with '..'",
    REASON_OUTSIDE: "it is not in a folder Nerva may send from",
    REASON_SYMLINK: "it is a link, and links are never followed",
    REASON_PROTECTED: "it is in a protected folder",
    REASON_SECRET_NAME: "its name looks like a secret or a data store",
    REASON_NOT_FILE: "it is not a regular file",
    REASON_MISSING: "it does not exist",
    REASON_TOO_LARGE: "it is larger than the attachment limit",
    REASON_EMPTY: "it is empty",
    REASON_UNREADABLE: "it could not be read",
    REASON_TOO_MANY: "a reply carries at most four files",
    REASON_HARDLINK: "it has other names (hard links), so where it really lives cannot be checked",
    REASON_TIMEOUT: "checking it took too long",
}


@dataclass(frozen=True)
class DeliverableFile:
    """One file that passed every rule, read once into memory."""

    name: str
    data: bytes
    mime: str
    sha256: str

    @property
    def kind(self) -> str:
        """``image`` / ``audio`` / ``video`` / ``document`` — how a channel attaches it."""
        major = self.mime.split("/", 1)[0]
        return major if major in ("image", "audio", "video") else "document"


@dataclass(frozen=True)
class Refusal:
    reason: str

    @property
    def text(self) -> str:
        return REFUSAL_TEXT.get(self.reason, "it may not be sent")


def max_bytes() -> int:
    return min(env_int(MAX_BYTES_ENV, DEFAULT_MAX_BYTES, minimum=1), MAX_BYTES_CEILING)


def _real(path: Path) -> Path | None:
    try:
        return Path(os.path.realpath(path))
    except (OSError, ValueError):
        return None


def _within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def protected_roots() -> list[Path]:
    """Folders a delivery root may never be, or contain, and files are never sent from."""
    from ..paths import data_path

    roots = [data_path("security"), data_path("tokens"), data_path("vault"),
             data_path("secrets"), data_path("config")]
    return [r for r in (_real(p) for p in roots) if r is not None]


#: Folders in the home directory that hold credentials or settings: a delivery root may
#: never be inside one either.
_HOME_PRIVATE = (".ssh", ".gnupg", ".config", ".aws", ".kube", ".docker", ".netrc",
                 ".password-store", ".local/share/keyrings")


def _private_home_dirs() -> list[Path]:
    home = _real(Path.home())
    return [home / name for name in _HOME_PRIVATE] if home is not None else []


def _forbidden_root_parents() -> list[Path]:
    """A delivery root that is or contains any of these is refused outright."""
    from ..paths import data_root

    candidates = [Path(os.sep), Path.home(), data_root(), Path(__file__).resolve().parents[3]]
    return [r for r in (_real(p) for p in candidates) if r is not None] + protected_roots()


def _default_roots() -> list[Path]:
    from ..paths import data_path

    return [data_path("outputs"), data_path("media", "generated"), data_path("reports")]


def allowed_roots() -> list[Path]:
    """The resolved delivery roots in effect now (existing directories only)."""
    roots: list[Path] = []
    forbidden = _forbidden_root_parents()
    configured = [p for p in env_str(DIRS_ENV).split(os.pathsep) if p.strip()]
    for raw, owner_listed in [(p, False) for p in _default_roots()] + [(p, True) for p in configured]:
        candidate = Path(str(raw).strip()).expanduser() if owner_listed else Path(raw)
        if not candidate.is_absolute():
            logger.warning("%s: an entry is not an absolute path; ignored", DIRS_ENV)
            continue
        real = _real(candidate)
        if real is None or not real.is_dir():
            continue
        # A root may not BE a protected place nor CONTAIN one (it would expose it).
        if any(real == bad or _within(bad, real) for bad in forbidden):
            logger.warning("%s: an entry is or contains a protected folder; ignored", DIRS_ENV)
            continue
        if any(_within(real, bad) for bad in protected_roots() + _private_home_dirs()):
            logger.warning("%s: an entry is inside a protected or private folder; ignored", DIRS_ENV)
            continue
        if real not in roots:
            roots.append(real)
    return roots


def _guess_mime(name: str, head: bytes) -> str:
    """The type the bytes prove, else the name's guess. A name-guessed audio type only
    labels the file: ``audio_container.prepare_voice`` decides from the bytes whether it is
    audio at all, and hands ffmpeg nothing it did not recognise (a ``.flac`` that is a
    DASH manifest goes out as a plain document)."""
    from ..artifact_store import sniff
    from .audio_container import MIME as AUDIO_MIME
    from .audio_container import sniff as sniff_audio

    try:
        return sniff(head)
    except Exception:  # noqa: BLE001 — sniff knows a short list; try audio, then the name
        container = sniff_audio(head)
        if container in AUDIO_MIME:
            return AUDIO_MIME[container]
        guessed, _ = mimetypes.guess_type(name)
        return guessed or "application/octet-stream"


_DIR_FLAGS = (os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
              | getattr(os, "O_CLOEXEC", 0))
_FILE_FLAGS = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
               | getattr(os, "O_CLOEXEC", 0))


def _open_beneath(root: Path, parts: tuple[str, ...]) -> int:
    """Open ``root/parts…`` one component at a time, each relative to the directory
    opened before it and with ``O_NOFOLLOW``: a folder swapped for a link at any moment
    fails the walk instead of being followed (openat2 RESOLVE_BENEATH, portably). The
    file itself opens non-blocking, so a FIFO or device cannot hold the call."""
    fd = os.open(root, _DIR_FLAGS)
    try:
        for part in parts[:-1]:
            nxt = os.open(part, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return os.open(parts[-1], _FILE_FLAGS, dir_fd=fd)
    finally:
        os.close(fd)


def resolve(path: str, *, roots: list[Path] | None = None) -> DeliverableFile | Refusal:
    """Check *path* against every rule and read it, or say why it may not be sent."""
    if not isinstance(path, str) or not path or len(path) > _MAX_PATH or "\x00" in path:
        return Refusal(REASON_NOT_ABSOLUTE)
    raw = Path(path.strip())
    if not raw.is_absolute():
        return Refusal(REASON_NOT_ABSOLUTE)
    if ".." in raw.parts:
        return Refusal(REASON_TRAVERSAL)
    roots = allowed_roots() if roots is None else [r for r in (_real(p) for p in roots) if r]
    lexical = Path(os.path.normpath(raw))
    # The lexical path must already be under a root (as the owner configured it, or its
    # resolved form), and the resolved path must be too: no link may lead out.
    real = _real(lexical)
    if real is None:
        return Refusal(REASON_MISSING)
    if not any(_within(real, root) for root in roots):
        return Refusal(REASON_OUTSIDE)
    if any(_within(real, bad) for bad in protected_roots()):
        return Refusal(REASON_PROTECTED)
    try:
        st = os.lstat(lexical)
    except FileNotFoundError:
        return Refusal(REASON_MISSING)
    except OSError:
        return Refusal(REASON_UNREADABLE)
    if stat.S_ISLNK(st.st_mode):
        return Refusal(REASON_SYMLINK)
    if not stat.S_ISREG(st.st_mode):   # a FIFO, socket or device is never opened
        return Refusal(REASON_NOT_FILE)
    root = next(r for r in roots if _within(real, r))
    rel_parts = real.relative_to(root).parts
    if not rel_parts:
        return Refusal(REASON_NOT_FILE)
    if any(part.startswith(".") for part in rel_parts):
        return Refusal(REASON_PROTECTED)
    if _SECRET_NAME.search(real.name.lower()):
        return Refusal(REASON_SECRET_NAME)
    limit = max_bytes()
    try:
        fd = _open_beneath(root, rel_parts)
    except FileNotFoundError:
        return Refusal(REASON_MISSING)
    except OSError:
        # ELOOP / ENOTDIR: a component became a link (or something else) on the way.
        return Refusal(REASON_SYMLINK)
    try:
        fst = os.fstat(fd)
        if not stat.S_ISREG(fst.st_mode):
            return Refusal(REASON_NOT_FILE)
        if (fst.st_ino, fst.st_dev) != (st.st_ino, st.st_dev):
            # The path checked and the file opened are not the same file.
            return Refusal(REASON_SYMLINK)
        if fst.st_nlink > 1:
            # A hard link can carry a protected file into an approved folder.
            return Refusal(REASON_HARDLINK)
        if fst.st_size > limit:
            return Refusal(REASON_TOO_LARGE)
        if fst.st_size == 0:
            return Refusal(REASON_EMPTY)
        os.set_blocking(fd, True)   # a regular file: ordinary reads from here
        chunks, total = [], 0
        while True:
            block = os.read(fd, 1 << 16)
            if not block:
                break
            total += len(block)
            if total > limit:   # the file grew after fstat
                return Refusal(REASON_TOO_LARGE)
            chunks.append(block)
    except OSError:
        return Refusal(REASON_UNREADABLE)
    finally:
        os.close(fd)
    data = b"".join(chunks)
    if not data:
        return Refusal(REASON_EMPTY)
    name = re.sub(r"[^A-Za-z0-9._-]", "_", real.name)[:96] or "file"
    return DeliverableFile(name=name, data=data, mime=_guess_mime(name, data),
                           sha256=hashlib.sha256(data).hexdigest())


def extract_directives(text: str) -> tuple[str, list[str]]:
    """Split a reply into its words and the ``MEDIA:`` paths it names (in order, unique).

    Only a line of its own outside a fenced code block counts: an example in a code
    block or a quoted line (``> MEDIA: …``) is text and stays as it is."""
    if not isinstance(text, str) or "MEDIA:" not in text:
        return text, []
    paths: list[str] = []
    kept: list[str] = []
    fenced = False
    for line in text.split("\n"):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            kept.append(line)
            continue
        match = None if fenced else _DIRECTIVE.fullmatch(line.rstrip("\r"))
        if match is None:
            kept.append(line)
            continue
        found = match.group("path").strip().strip("`'\"")
        if found and found not in paths:
            paths.append(found)
    if not paths:
        return text, []
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    return cleaned, paths


def strip_partial(text: str) -> str:
    """For a reply still being written: drop finished ``MEDIA:`` lines and hold back a
    last line that may become one, so a path is never shown while streaming."""
    if not isinstance(text, str):
        return text
    lines = text.split("\n")
    last = lines.pop()
    shown = [line for line in lines if not _DIRECTIVE.fullmatch(line.rstrip("\r"))]
    head = last.lstrip()
    if not head or not ("MEDIA:".startswith(head) or head.startswith("MEDIA:")):
        shown.append(last)
    return "\n".join(shown)


def refusal_line(index: int, refusal: Refusal) -> str:
    return f"Attachment {index} was not sent: {refusal.text}."


__all__ = [
    "DIRS_ENV", "DeliverableFile", "MAX_BYTES_ENV", "MAX_FILES_PER_REPLY", "REFUSAL_TEXT",
    "Refusal", "allowed_roots", "extract_directives", "max_bytes", "protected_roots",
    "refusal_line", "resolve", "strip_partial",
]
