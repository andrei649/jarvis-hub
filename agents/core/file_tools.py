"""file_tools.py — governed file tools reachable from the model loop (H20.R1).

Productivity work is mostly files, so the model-directed tool loop gets five
tools that are *governed by construction*:

  * ``file_read`` / ``file_list`` / ``file_search`` — ungated, but only inside
    the owner's :class:`FileScope` (resolved roots, no ``..`` traversal, no
    symlink escape, no secret-looking names) and bounded in bytes / entries /
    matches. ``file_search`` (Hermes absorption 3a) is a *literal* search on
    purpose: a regex has no time bound in Python's ``re``, so one pathological
    pattern from the model would pin the host CPU and block the tool loop, and
    ripgrep would make the tool depend on a binary a fresh Windows or macOS
    install does not have. A literal scan is linear by construction.
  * ``file_write`` / ``file_delete`` — gated ToolRPC tools (``gated=True``,
    ``trusted_execution=True``): a call from the sandbox never writes inline;
    it enqueues an ask-tier ``toolrpc.file_write`` task after ``tool.rpc`` kernel
    mediation, and the handler runs only from the approved task's execution.
    Every write/delete first snapshots the previous bytes so it is reversible
    by construction (``snapshot_ref`` → :func:`restore_snapshot`).

Governance (MOONSHOT §5):

* The privileged effect is the action kind :data:`KIND` (``file.write``, also
  used for deletes with ``op='delete'``). Its admissibility is
  :data:`FILE_WRITE_CONTRACT` (path inside roots, bytes ≤ cap, a snapshot
  reference). An *injected* kernel ``authorizer`` (``authorize(Action) ->
  Decision``) is consulted before the bytes move; a DENY refuses, a QUEUE
  refuses unless the call arrives through the approved-execution path
  (``approved=True`` is set only by :func:`register_file_tools`' closure, which
  the ToolRPC server reaches solely from :meth:`ToolRPCServer.execute`).
  Nothing here self-authorizes; the kernel registration itself is the
  integrator's edit (see the slice report).
* H506 (write half) — a file that *steers a future run* (``SOUL.md``,
  ``AGENTS.md``, ``CLAUDE.md``, ``GEMINI.md``, ``HEARTBEAT.md``, each with its
  gitignored ``.local`` overlay, plus ``.cursorrules`` and Cursor's ``*.mdc`` rules;
  see :data:`INSTRUCTION_FILE_NAMES`) is its own class on top of
  that contract, enforced in two places that are **not** the same strength:

  1. *On the production path*, :func:`register_file_tools` registers
     :meth:`FileTools.classify_mutation` as the ToolRPC ``classifier`` for both
     gated tools. The approval card the owner reads then names the class
     (``class='agent_instructions'``, title ``… — this file steers future runs``)
     instead of being byte-identical to a write to a scratch note, and
     :meth:`ToolRPCServer.execute` re-derives the class from the args about to run
     and refuses (``approval_class_mismatch``) unless the approved card carried it.
     So an instruction-file write executes only off an approval that told the
     owner what it was. This holds with the kernel off, which is the default, and
     no caller can pass it — the handler is never reached.
  2. *On this module's own API*, :meth:`FileTools._mutate` additionally refuses an
     instruction-file mutation without ``approved=True``, whatever the kernel says
     and whether or not it is on. This one is defense-in-depth for a future
     in-process caller of ``write_file`` / ``delete_file``; the shipped ToolRPC
     path passes it **by design**, because it only runs after the owner decided
     the card. It is therefore weaker than ``skill.install``'s permanent owner
     floor (:meth:`PromotionBroker.propose`), which has no caller-supplied flag at
     all — do not read the two as the same guarantee.

  Not shipped here: the *read* half. ``Agent._load_soul`` still splices
  ``SOUL.md`` into the system prompt with no injection scan — a separate change
  that needs a product decision about what a blocked SOUL means.
* Default-off: :func:`register_file_tools` is a no-op unless
  ``JARVIS_FILE_TOOLS`` is set. Roots come from ``JARVIS_FILE_ROOTS``
  (default ``data_path('workspace')``); the byte cap from
  ``JARVIS_FILE_MAX_BYTES`` (default 2 000 000).
* H661 — ``file_read`` pages (``offset`` / ``next_offset``), and the coordinator may
  hand it the tool-result spill directory as a read-only door (``spill_dirs``): an
  exact, absolute spill-file path is readable even when ``JARVIS_FILE_ROOTS`` points
  elsewhere, so the call a spilled result's notice names is one this tool accepts.
  Nothing is listed, searched or written through that door (:meth:`FileTools._spill_file`).
  A page of a spill, by either route, declares ``tainted``: the loop fences it and
  marks the turn as it did when the tool first answered (:meth:`FileTools._is_spill`).
* Local-first, no new dependencies, no shell; blocking file I/O runs in
  ``asyncio.to_thread`` so the event loop stays free.

Snapshots live under ``data_path('file_tools', 'snapshots')`` (never CWD):
``blobs/<sha256>`` holds the previous bytes (content-addressed) and
``<ref>.json`` the record (path, blob sha, whether the file existed, mode). A
``ref`` is the SHA-256 of the record's canonical JSON, so a tampered record no
longer matches its reference and restore refuses.
"""

from __future__ import annotations

import asyncio
import contextlib
import fnmatch
import hashlib
import json
import logging
import os
import stat
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.core import project_context
from agents.core.automation_contracts import ContractTemplate, predicate
from agents.core.env_config import env_flag, env_int, env_list
from agents.core.environments import SECRET_ENV_SUBSTRINGS
from agents.core.local_docs import DOC_EXTS, extract_text
from agents.core.paths import data_path
from agents.core.tool_result_store import SPILL_DIRNAME as _SPILL_DIRNAME
from agents.core.tool_result_store import is_reference as _is_spill_reference
from agents.core.tool_rpc import ToolRPCValidationError

logger = logging.getLogger("jarvis.file_tools")

# ── vocabulary ───────────────────────────────────────────────────────────────

KIND = "file.write"
FLAG = "JARVIS_FILE_TOOLS"
ROOTS_ENV = "JARVIS_FILE_ROOTS"
MAX_BYTES_ENV = "JARVIS_FILE_MAX_BYTES"
DEFAULT_MAX_BYTES = 2_000_000
MAX_PATH_CHARS = 4096
#: The largest ``file_read`` offset (H661): the largest integer every JSON reader holds
#: exactly, and far past any file. Above it an offset is refused as ``bad_offset``
#: rather than reaching ``seek``, which raises ``ValueError`` past 2**63 and ``EINVAL``
#: past the filesystem's own size limit — neither of which is the reader's business.
MAX_OFFSET = 2**53 - 1
MAX_LIST_ENTRIES = 2000
# Hermes absorption 4h — a .pdf / .docx inside the roots is read as its text, through the
# same optional parsers the local-docs indexer uses (pypdf, python-docx); without them the
# refusal names the missing parser instead of handing the model a page of replacement
# characters. ``raw=true`` still returns the bytes.
DOCUMENT_SUFFIXES = frozenset(DOC_EXTS)
_DOCUMENT_PARSERS = {".pdf": "pypdf", ".docx": "docx"}
DEFAULT_LIST_ENTRIES = 500
# file_search bounds. Each is a ceiling the result reports hitting (``truncated``
# plus ``stopped_by``) rather than a silent edge of the workspace.
MAX_PATTERN_CHARS = 512
MAX_GLOB_CHARS = 128
MAX_SEARCH_MATCHES = 500
DEFAULT_SEARCH_MATCHES = 50
MAX_MATCHES_PER_FILE = 20
MAX_SEARCH_FILES = 5000
MAX_SEARCH_SECONDS = 10.0
MATCH_LINE_CHARS = 8192
SNIPPET_CHARS = 200
_BINARY_PROBE_BYTES = 8192

# Names that are secrets by convention. A file whose *name* matches is refused
# for every operation, even inside the roots (the roots are a workspace, not a
# licence to read ``.env``). A name token (split on ``.``/``-``/``_``/space,
# upper-cased) equal to one of the SECRET_ENV_SUBSTRINGS (KEY, TOKEN, SECRET,
# PASSWORD, ...), its plural, or a well-known compound (APIKEY, ACCESSTOKEN,
# CLIENTSECRET, ...) refuses — whole tokens, so ``keyboard.md`` / ``authors.txt``
# stay readable while ``api_key.txt`` / ``secrets.json`` do not. So does an exact
# filename or extension from the lists below, and any secret directory
# component (``.ssh``, ``.aws``, ...). A doubtful case refuses — the safe side.
SECRET_FILE_NAMES = frozenset({
    ".env", ".envrc", ".netrc", ".npmrc", ".pypirc", ".htpasswd", ".pgpass",
    ".git-credentials", "credentials", "credentials.json", "secrets.yaml",
    "secrets.yml", "secrets.json", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    "known_hosts", "authorized_keys", "shadow", "master.key",
})
SECRET_FILE_PREFIXES = (".env.", "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa")
SECRET_FILE_SUFFIXES = (
    ".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".kdbx", ".asc", ".gpg",
    ".ppk", ".ovpn",
)
SECRET_PATH_PARTS = frozenset({
    ".ssh", ".aws", ".gnupg", ".azure", ".kube", ".docker", ".password-store",
    "Keychains", ".config/gcloud", ".git",
})

SECRET_NAME_TOKENS = frozenset(
    {word for base in SECRET_ENV_SUBSTRINGS for word in (base, f"{base}S")}
    | {
        "APIKEY", "APIKEYS", "ACCESSKEY", "SECRETKEY", "PRIVATEKEY", "PRIVKEY",
        "ACCESSTOKEN", "AUTHTOKEN", "REFRESHTOKEN", "IDTOKEN", "CLIENTSECRET",
        "PASSWD", "CREDS", "KEYRING", "KEYCHAIN", "WALLET", "SEEDPHRASE", "MNEMONIC",
    }
)

_SCOPE_REASONS = frozenset({
    "bad_path", "outside_scope", "symlink_escape", "secret_path",
})


class FileScopeError(ValueError):
    """A path was refused by the scope; ``reason`` is a bounded public code."""

    def __init__(self, reason: str) -> None:
        self.reason = reason if reason in _SCOPE_REASONS else "bad_path"
        super().__init__(self.reason)


# ── secret-name policy ───────────────────────────────────────────────────────

def _name_tokens(name: str) -> list[str]:
    out: list[str] = []
    current: list[str] = []
    for ch in name.upper():
        if ch.isalnum():
            current.append(ch)
        elif current:
            out.append("".join(current))
            current = []
    if current:
        out.append("".join(current))
    return out


def looks_secret_name(name: str) -> bool:
    """True when a file/dir *name* is a secret by convention (see module doc)."""
    lowered = str(name or "").lower()
    if not lowered:
        return False
    if lowered in SECRET_FILE_NAMES or lowered in {p.lower() for p in SECRET_PATH_PARTS}:
        return True
    if lowered.startswith(SECRET_FILE_PREFIXES) or lowered.endswith(SECRET_FILE_SUFFIXES):
        return True
    return any(token in SECRET_NAME_TOKENS for token in _name_tokens(lowered))


def _has_secret_part(relative_parts: Sequence[str]) -> bool:
    joined = "/".join(relative_parts)
    for part in SECRET_PATH_PARTS:
        if "/" in part:
            if f"/{joined}/".find(f"/{part}/") >= 0:
                return True
        elif part in relative_parts:
            return True
    return any(looks_secret_name(part) for part in relative_parts)


# ── instruction-file policy (H506) ───────────────────────────────────────────

# Files whose *contents* steer a future run. ``Agent._load_soul``
# (agents/core/agent.py) reads ``SOUL.local.md`` → ``SOUL.md`` straight into the
# system prompt, and the assistant harnesses around this repo load ``AGENTS.md``
# / ``CLAUDE.md`` / ``GEMINI.md`` / ``.cursorrules`` / ``.cursor/rules/*.mdc`` as
# standing instructions.
# Writing one of these is not an ordinary edit — it is an edit to what Nerva will
# be *told to do* next time — so it is its own class layered on top of
# ``file.write``: the owner's approval card names it, and the approved execution
# is refused unless the card did (see the module docstring for which half of this
# is on the production path and which is defense-in-depth on this API).
#
# Matched on the *basename*, in any directory inside the roots: an instruction
# file is wherever the harness that reads it looks, and ``_load_soul`` alone
# searches three roots. The trade is deliberate and known — an owner-legitimate
# note called ``claude.md`` anywhere in the workspace now always asks — and
# asking is the side of that trade to be wrong on.
#
# The gitignored ``.local`` overlay is part of the *rule*, not an extra name: every
# loader here prefers ``<name>.local.md`` over ``<name>.md`` when it exists —
# ``Agent._load_soul`` for ``SOUL.local.md``, ``core/heartbeat.py`` for
# ``HEARTBEAT.local.md`` (whose contents become CRON-SCHEDULED agent runs), the
# assistant harnesses for ``CLAUDE.local.md`` / ``AGENTS.local.md``. So the overlays are
# *derived* from the roster below instead of being listed one by one: a name added here
# brings its overlay with it, and none can be forgotten. The first cut spelled two of
# them out by hand, which left ``CLAUDE.local.md`` — same authority, same loader — asking
# with the title of a scratch note.
INSTRUCTION_BASE_NAMES = frozenset({
    "soul.md", "agents.md", "claude.md", "gemini.md", ".cursorrules", "heartbeat.md",
    # H670: the shared behaviour contract every agent's system prompt starts with
    # (``Agent.identity_path``), and with it ``identity.local.md``, the per-install override.
    "identity.md",
})


def _local_overlay(name: str) -> str | None:
    """``claude.md`` → ``claude.local.md``; ``None`` for a name with no stem to overlay."""
    stem, dot, ext = name.rpartition(".")
    return f"{stem}.local.{ext}" if stem and dot else None


#: The roster plus the ``.local`` overlay of every name that has one.
INSTRUCTION_FILE_NAMES = frozenset(INSTRUCTION_BASE_NAMES).union(
    overlay for overlay in map(_local_overlay, INSTRUCTION_BASE_NAMES) if overlay
)
#: Cursor's *current* rules format — ``.cursor/rules/<anything>.mdc`` — which superseded
#: the single ``.cursorrules`` file the roster already covers. Those rule files are named
#: freely, so this half of the class is matched by extension: an ``.mdc`` file is a rules
#: file by convention, and it is read as standing instructions like the rest.
INSTRUCTION_FILE_SUFFIXES = (".mdc",)
INSTRUCTION_CLASS = "agent_instructions"
#: The one line the owner reads on the approval card. It is the whole point of the
#: class: the ask for SOUL.md must not look like the ask for a scratch note.
INSTRUCTION_NOTICE = "this file steers future runs"


def looks_instruction_name(name: object) -> bool:
    """True when a file *name* is one a future run is steered by (case-insensitive)."""
    lowered = str(name or "").strip().lower()
    if not lowered:
        return False
    return lowered in INSTRUCTION_FILE_NAMES or lowered.endswith(INSTRUCTION_FILE_SUFFIXES)


def instruction_labels(*names: object) -> dict[str, Any] | None:
    """The H506 class labels when any of *names* steers a future run, else ``None``.

    One builder for both sides of the approval — the card :meth:`ToolRPCServer.handle`
    enqueues and the floor inside :meth:`FileTools._mutate` — so the two can never
    disagree about what is in the class.
    """
    if not any(looks_instruction_name(name) for name in names):
        return None
    return {
        "class": INSTRUCTION_CLASS,
        "steers_future_runs": True,
        "notice": INSTRUCTION_NOTICE,
    }


def _requested_name(raw_path: object) -> str:
    """The basename as the caller spelled it, *before* symlink resolution.

    :meth:`FileScope.resolve` already returns a fully realpath-ed target, so a
    write aimed at ``notes.md`` that is a symlink to ``SOUL.md`` arrives here
    already named ``SOUL.md`` — the resolved name covers that direction. The
    reverse it does not cover: ``SOUL.md`` symlinked onto ``real.md`` resolves to
    ``real.md``, while every harness still *reads* it through the ``SOUL.md``
    name. So the spelling the caller used is checked as well.
    """
    if not isinstance(raw_path, str) or not raw_path:
        return ""
    try:
        return Path(raw_path).name
    except (OSError, ValueError):  # pragma: no cover - defensive
        return ""


# ── scope ────────────────────────────────────────────────────────────────────

class FileScope:
    """The owner-configured roots every file tool must stay inside."""

    def __init__(self, roots: Sequence[str | Path]) -> None:
        resolved: list[Path] = []
        for raw in roots or ():
            text = str(raw or "").strip()
            if not text:
                continue
            root = Path(text).expanduser()
            if not root.is_absolute():
                raise ValueError("file roots must be absolute paths")
            resolved.append(root.resolve())
        if not resolved:
            raise ValueError("file scope needs at least one root")
        self._roots: tuple[Path, ...] = tuple(dict.fromkeys(resolved))

    @classmethod
    def from_env(cls) -> FileScope:
        roots = env_list(ROOTS_ENV) or [str(data_path("workspace"))]
        return cls(roots)

    @property
    def roots(self) -> tuple[Path, ...]:
        return self._roots

    def root_for(self, path: Path) -> Path | None:
        for root in self._roots:
            if path == root or root in path.parents:
                return root
        return None

    def resolve(self, path: object) -> Path:
        """Resolve *path* (absolute, or relative to the first root) inside the scope.

        Refuses with :class:`FileScopeError`: ``bad_path`` (not a bounded string),
        ``outside_scope`` (lexically outside every root — ``..`` traversal
        included), ``symlink_escape`` (lexically inside, but a symlink points out)
        and ``secret_path`` (a secret-looking name or directory component).
        """
        if not isinstance(path, str) or not path or len(path) > MAX_PATH_CHARS:
            raise FileScopeError("bad_path")
        if "\x00" in path or path != path.strip():
            raise FileScopeError("bad_path")
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self._roots[0] / candidate
        lexical = Path(os.path.normpath(str(candidate)))
        if self.root_for(lexical) is None:
            raise FileScopeError("outside_scope")
        try:
            resolved = lexical.resolve()
        except (OSError, RuntimeError):
            raise FileScopeError("bad_path") from None
        root = self.root_for(resolved)
        if root is None:
            raise FileScopeError("symlink_escape")
        relative = resolved.relative_to(root).parts
        if _has_secret_part(relative):
            raise FileScopeError("secret_path")
        return resolved


# ── the write contract (the kernel kind's admissibility) ─────────────────────

def _file_write_contract_template() -> ContractTemplate:
    def right_kind(view, now):
        return view.get("kind") == KIND

    def known_op(view, now):
        return view.get("op") in ("write", "delete")

    def path_is_absolute(view, now):
        path = view.get("path")
        return isinstance(path, str) and bool(path) and Path(path).is_absolute()

    def path_inside_roots(view, now):
        path = view.get("path")
        root = view.get("root")
        if not isinstance(path, str) or not isinstance(root, str) or not root:
            return False
        resolved = Path(path)
        root_path = Path(root)
        return resolved == root_path or root_path in resolved.parents

    def bytes_within_cap(view, now):
        size = view.get("bytes")
        cap = view.get("max_bytes")
        if isinstance(size, bool) or isinstance(cap, bool):
            return False
        return isinstance(size, int) and isinstance(cap, int) and 0 <= size <= cap

    def has_snapshot_ref(view, now):
        ref = view.get("snapshot_ref")
        return isinstance(ref, str) and len(ref) == 64 and all(
            ch in "0123456789abcdef" for ch in ref
        )

    return ContractTemplate(kind="file_write", constraints=(
        predicate("right_kind", right_kind, reason="invalid_kind"),
        predicate("known_op", known_op, reason="invalid_op"),
        predicate("path_is_absolute", path_is_absolute, reason="bad_path"),
        predicate("path_inside_roots", path_inside_roots, reason="outside_scope"),
        predicate("bytes_within_cap", bytes_within_cap, reason="too_large"),
        predicate("has_snapshot_ref", has_snapshot_ref, reason="missing_snapshot"),
    ), description=(
        "Admissibility for a governed file write/delete: inside the owner's roots, "
        "under the byte cap, and reversible through a recorded snapshot."
    ))


FILE_WRITE_CONTRACT = _file_write_contract_template()


# ── snapshots ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Snapshot:
    """What a write/delete replaced; enough to put the file back exactly."""

    path: str
    existed: bool
    blob_sha: str
    size: int
    mode: int
    created_at: float

    def __post_init__(self) -> None:
        if not self.path or not Path(self.path).is_absolute():
            raise ValueError("snapshot path must be absolute")
        if len(self.blob_sha) != 64 or any(c not in "0123456789abcdef" for c in self.blob_sha):
            raise ValueError("snapshot blob sha must be hex sha256")
        if isinstance(self.size, bool) or not isinstance(self.size, int) or self.size < 0:
            raise ValueError("snapshot size must be a non-negative int")
        if isinstance(self.mode, bool) or not isinstance(self.mode, int) or self.mode < 0:
            raise ValueError("snapshot mode must be a non-negative int")

    def canonical(self) -> str:
        return json.dumps({
            "path": self.path,
            "existed": self.existed,
            "blob_sha": self.blob_sha,
            "size": self.size,
            "mode": self.mode,
            "created_at": self.created_at,
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    @property
    def ref(self) -> str:
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()


def _is_ref(ref: object) -> bool:
    return isinstance(ref, str) and len(ref) == 64 and all(
        c in "0123456789abcdef" for c in ref
    )


class SnapshotStore:
    """Content-addressed blobs + fingerprinted records on the local disk."""

    def __init__(self, directory: Path | None = None) -> None:
        self._dir = Path(directory) if directory is not None else data_path(
            "file_tools", "snapshots"
        )

    @property
    def directory(self) -> Path:
        return self._dir

    def _blob_path(self, sha: str) -> Path:
        return self._dir / "blobs" / sha

    def _record_path(self, ref: str) -> Path:
        return self._dir / f"{ref}.json"

    def take(self, target: Path, *, now: float | None = None) -> Snapshot:
        """Record what is at *target* right now (or that nothing is)."""
        existed = target.exists()
        data = b""
        mode = 0
        if existed:
            info = target.stat()
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("not_a_file")
            data = target.read_bytes()
            mode = stat.S_IMODE(info.st_mode)
        sha = hashlib.sha256(data).hexdigest()
        snap = Snapshot(
            path=str(target), existed=existed, blob_sha=sha, size=len(data),
            mode=mode, created_at=float(time.time() if now is None else now),
        )
        blobs = self._dir / "blobs"
        blobs.mkdir(parents=True, exist_ok=True)
        blob = self._blob_path(sha)
        if not blob.exists():
            _atomic_write(blob, data, mode=0o600)
        _atomic_write(self._record_path(snap.ref), snap.canonical().encode("utf-8"), mode=0o600)
        return snap

    def load(self, ref: str) -> Snapshot | None:
        if not _is_ref(ref):
            return None
        record = self._record_path(ref)
        try:
            raw = json.loads(record.read_text(encoding="utf-8"))
            snap = Snapshot(
                path=str(raw["path"]), existed=bool(raw["existed"]),
                blob_sha=str(raw["blob_sha"]), size=int(raw["size"]),
                mode=int(raw["mode"]), created_at=float(raw["created_at"]),
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if snap.ref != ref:
            logger.warning("file snapshot record fingerprint mismatch: %s", ref)
            return None
        return snap

    def blob(self, snap: Snapshot) -> bytes | None:
        try:
            data = self._blob_path(snap.blob_sha).read_bytes()
        except OSError:
            return None
        if hashlib.sha256(data).hexdigest() != snap.blob_sha:
            logger.warning("file snapshot blob digest mismatch: %s", snap.blob_sha)
            return None
        return data


def _atomic_write(target: Path, data: bytes, *, mode: int | None = None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".nerva-", dir=str(target.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


# ── the tools ────────────────────────────────────────────────────────────────

def _bounded_int(value: object, default: int, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(minimum, min(maximum, value))


def _valid_offset(value: object) -> bool:
    """An int in ``0..MAX_OFFSET`` — not a bool, not a float, not a string of digits."""
    return (not isinstance(value, bool) and isinstance(value, int)
            and 0 <= value <= MAX_OFFSET)


async def _with_project_context(result: dict, target: Path) -> dict:
    """H594 — a read tool's result carries the convention files of *target*'s directory
    chain the turn has not been given (tainted, so the loop fences it); off the loop."""
    if project_context.current() is None:
        return result
    return await asyncio.to_thread(project_context.attach, result, target)


class FileTools:
    """Scope-bound file handlers. ``authorizer`` is the injected kernel hook."""

    def __init__(
        self,
        scope: FileScope | None = None,
        *,
        snapshots: SnapshotStore | None = None,
        max_bytes: int | None = None,
        authorizer: Callable[..., Any] | None = None,
        audit: Any = None,
        agent: str = "jarvis",
        spill_dirs: Sequence[str | Path] = (),
    ) -> None:
        self.scope = scope if scope is not None else FileScope.from_env()
        self.snapshots = snapshots if snapshots is not None else SnapshotStore()
        cap = max_bytes if max_bytes is not None else env_int(
            MAX_BYTES_ENV, DEFAULT_MAX_BYTES, minimum=1
        )
        if isinstance(cap, bool) or not isinstance(cap, int) or cap < 1:
            raise ValueError("max_bytes must be a positive int")
        self.max_bytes = cap
        self._authorizer = authorizer
        self._audit = audit
        self.agent = agent
        # H661 — directories of Nerva's own spilled tool results that `file_read` (and
        # nothing else) may open *by exact spill name* even when the owner's roots do
        # not contain them. Empty by default: only the coordinator, which writes the
        # spills and hands their paths to the model, opens this door.
        dirs: list[Path] = []
        for raw in spill_dirs or ():
            text = str(raw or "").strip()
            if not text:
                continue
            directory = Path(text).expanduser()
            if not directory.is_absolute():
                raise ValueError("spill directories must be absolute paths")
            dirs.append(directory.resolve())
        self._spill_dirs: tuple[Path, ...] = tuple(dict.fromkeys(dirs))

    @classmethod
    def from_env(cls, *, authorizer: Callable[..., Any] | None = None, audit: Any = None,
                 spill_dirs: Sequence[str | Path] = ()) -> FileTools:
        return cls(FileScope.from_env(), authorizer=authorizer, audit=audit,
                   spill_dirs=spill_dirs)

    # ── what file_read may open ──────────────────────────────────────────────

    def _spill_file(self, raw_path: object) -> Path | None:
        """The spill file *raw_path* names, or ``None`` — the read-only door (H661).

        A spilled result's notice names its file by absolute path; an owner who set
        ``JARVIS_FILE_ROOTS`` has, without meaning to, moved that path outside the
        scope, and the model is back to re-running the tool. So a path is admitted
        here — for ``file_read`` only — when all of these hold, and refused otherwise:

        * it is absolute and already normal (no ``..``, no symlinked spelling: the
          path must equal its own resolution, which is what the store emits);
        * its parent *is* one of the configured spill directories — never a child of
          one, so nothing nested is reachable;
        * its name has the store's reference shape (``<tool>-<hash>.json|txt``) and
          does not look like a secret by the scope's own rule.

        Nothing is listed or searched through this door and nothing is written: the
        name is only known to a turn that was told it.
        """
        if not self._spill_dirs or not isinstance(raw_path, str) or not raw_path:
            return None
        if len(raw_path) > MAX_PATH_CHARS or "\x00" in raw_path or raw_path != raw_path.strip():
            return None
        candidate = Path(raw_path)
        if not candidate.is_absolute() or str(candidate) != os.path.normpath(raw_path):
            return None
        name = candidate.name
        if not _is_spill_reference(name) or looks_secret_name(name):
            return None
        if candidate.parent not in self._spill_dirs:
            return None
        try:
            if candidate.resolve() != candidate:
                return None
        except (OSError, RuntimeError):
            return None
        return candidate

    def _resolve_read(self, raw_path: object) -> Path:
        """What ``file_read`` opens: the scope's answer, or a spill through the door.

        The scope's refusal stands unless the door admits the path, so a secret name,
        a symlink out of the roots or a traversal is refused exactly as before.
        """
        try:
            return self.scope.resolve(raw_path)
        except FileScopeError:
            spill = self._spill_file(raw_path)
            if spill is None:
                raise
            return spill

    def _is_spill(self, target: Path) -> bool:
        """True when *target* holds (part of) one of Nerva's spilled tool results (H661).

        A spill is a tool's output parked on disk: reading or searching it must not
        launder it into trusted file text. Its file name cannot say reliably which tool
        wrote it (names are sanitised, a secret-looking one is replaced), so every file
        directly in a spill directory counts as third-party — a finished spill, or a
        stream's temp file a crash left behind — in a configured spill directory or in
        any directory with the store's name, reached by the owner's roots or the door.
        The store writes nothing nested and no document types there, so a subfolder or
        a document read through the extractor is not covered (and not reachable today).
        """
        return target.parent in self._spill_dirs or target.parent.name == _SPILL_DIRNAME

    def reaches(self, raw_path: object) -> bool:
        """True when ``file_read`` would open *raw_path* now — the probe a notice asks
        before it names a call (H661). A refusal of any kind, or no file there, is no."""
        try:
            target = self._resolve_read(raw_path)
            return target.is_file()
        except (FileScopeError, OSError, ValueError):
            return False

    # ── ungated ──────────────────────────────────────────────────────────────

    async def read_file(self, args: Mapping[str, Any]) -> dict:
        """One bounded page of a file, starting at ``offset`` (H661).

        A read that stops before the end says where the next page starts
        (``next_offset``), so a file bigger than one page — a spilled tool result is
        the case this exists for — is reachable to its last byte without re-running
        whatever produced it. A bad ``offset`` — not an int, negative, or past
        :data:`MAX_OFFSET` — is refused by name: reading from 0 instead would return
        the first page labelled as the one that was asked for. An offset at or past
        the end is an empty final page, answered without seeking there. A page of a
        spilled tool result says ``tainted``, so the loop fences it and marks the turn
        exactly as it did when the tool first answered (:meth:`_is_spill`).
        """
        offset = args.get("offset")
        if offset is None:
            offset = 0
        elif not _valid_offset(offset):
            return {"ok": False, "reason": "bad_offset"}
        try:
            target = self._resolve_read(args.get("path"))
        except FileScopeError as exc:
            return {"ok": False, "reason": exc.reason}
        limit = _bounded_int(args.get("max_bytes"), self.max_bytes, minimum=1, maximum=self.max_bytes)
        raw = args.get("raw") is True

        def _read() -> dict:
            if not target.exists():
                return {"ok": False, "reason": "not_found"}
            if not target.is_file():
                return {"ok": False, "reason": "not_a_file"}
            size = target.stat().st_size
            if not raw and target.suffix.lower() in DOCUMENT_SUFFIXES:
                return _read_document(target, size, limit, offset)
            data = b""
            if offset < size:
                with target.open("rb") as handle:
                    handle.seek(offset)
                    data = handle.read(limit)
            page = {"ok": True, "path": str(target), **_page(data, offset=offset, total=size),
                    "size": size}
            if self._is_spill(target):
                page["tainted"] = True
            return page

        try:
            result = await asyncio.to_thread(_read)
        except (OSError, ValueError, OverflowError) as exc:
            return {"ok": False, "reason": "io_error", "detail": exc.__class__.__name__}
        self._record("file.read", str(target), ok=result.get("ok") is True)
        return await _with_project_context(result, target)   # H594

    async def list_dir(self, args: Mapping[str, Any]) -> dict:
        raw_path = args.get("path")
        if raw_path is None:
            raw_path = str(self.scope.roots[0])
        try:
            target = self.scope.resolve(raw_path)
        except FileScopeError as exc:
            return {"ok": False, "reason": exc.reason}
        limit = _bounded_int(
            args.get("max_entries"), DEFAULT_LIST_ENTRIES, minimum=1, maximum=MAX_LIST_ENTRIES
        )

        def _list() -> dict:
            if not target.exists():
                return {"ok": False, "reason": "not_found"}
            if not target.is_dir():
                return {"ok": False, "reason": "not_a_dir"}
            entries: list[dict] = []
            hidden = 0
            names = sorted(os.listdir(target))
            for name in names:
                if looks_secret_name(name):
                    hidden += 1
                    continue
                if len(entries) >= limit:
                    break
                child = target / name
                try:
                    info = child.lstat()
                except OSError:
                    continue
                if stat.S_ISLNK(info.st_mode):
                    kind = "symlink"
                elif stat.S_ISDIR(info.st_mode):
                    kind = "dir"
                elif stat.S_ISREG(info.st_mode):
                    kind = "file"
                else:
                    kind = "other"
                entries.append({"name": name, "type": kind, "size": int(info.st_size)})
            visible = len(names) - hidden
            return {
                "ok": True,
                "path": str(target),
                "entries": entries,
                "hidden": hidden,
                "truncated": visible > len(entries),
            }

        try:
            result = await asyncio.to_thread(_list)
        except OSError as exc:
            return {"ok": False, "reason": "io_error", "detail": exc.__class__.__name__}
        self._record("file.list", str(target), ok=result.get("ok") is True)
        return await _with_project_context(result, target)   # H594

    async def search_files(self, args: Mapping[str, Any]) -> dict:
        """Find lines containing *pattern* under *path* (a directory, or one file).

        A literal, linear scan with the read tools' containment and nothing more: it
        never follows a symlink, skips every secret-looking name (counted as
        ``hidden``), reads only regular files under the byte cap, skips binaries (a
        NUL in the first 8 KiB), matches each line on its first 8 KiB and returns a
        bounded snippet rather than the line. Matches, matches per file, files visited
        and wall-clock seconds are all capped; a search that hit a cap says
        ``truncated`` and names the cap in ``stopped_by`` instead of pretending the
        workspace ended there.
        """
        try:
            clean = _preflight_search(dict(args))
        except ToolRPCValidationError as exc:
            return {"ok": False, "reason": exc.reason}
        raw_path = clean.get("path")
        if raw_path is None:
            raw_path = str(self.scope.roots[0])
        try:
            target = self.scope.resolve(raw_path)
        except FileScopeError as exc:
            return {"ok": False, "reason": exc.reason}
        pattern = clean["pattern"]
        case_sensitive = bool(clean.get("case_sensitive", False))
        whole_word = bool(clean.get("whole_word", False))
        glob = clean.get("glob")
        limit = _bounded_int(
            clean.get("max_matches"), DEFAULT_SEARCH_MATCHES,
            minimum=1, maximum=MAX_SEARCH_MATCHES,
        )
        needle = pattern if case_sensitive else pattern.lower()
        root = self.scope.root_for(target) or target
        deadline = time.monotonic() + MAX_SEARCH_SECONDS

        def _search() -> dict:
            if not target.exists():
                return {"ok": False, "reason": "not_found"}
            if not (target.is_file() or target.is_dir()):
                return {"ok": False, "reason": "not_a_file"}
            matches: list[dict] = []
            tainted = False
            counts = {
                "files_scanned": 0, "files_matched": 0, "files_capped": 0, "hidden": 0,
                "binary": 0, "large": 0, "symlink": 0,
            }
            stopped_by: str | None = None
            for file, size in _walk_files(target, root, counts):
                if time.monotonic() > deadline:
                    stopped_by = "deadline"
                    break
                if counts["files_scanned"] >= MAX_SEARCH_FILES:
                    stopped_by = "max_files"
                    break
                if glob is not None and not fnmatch.fnmatchcase(file.name, glob):
                    continue
                if size > self.max_bytes:
                    counts["large"] += 1
                    continue
                with file.open("rb") as handle:
                    probe = handle.read(_BINARY_PROBE_BYTES)
                    if b"\x00" in probe:
                        counts["binary"] += 1
                        continue
                    data = probe + handle.read(max(0, self.max_bytes - len(probe)))
                counts["files_scanned"] += 1
                per_file = 0
                for lineno, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
                    hay = line[:MATCH_LINE_CHARS]
                    index = _find_literal(hay if case_sensitive else hay.lower(), needle, whole_word)
                    if index < 0:
                        continue
                    if per_file >= MAX_MATCHES_PER_FILE:
                        counts["files_capped"] += 1
                        break
                    per_file += 1
                    matches.append({
                        "path": str(file),
                        "line": lineno,
                        "text": _snippet(hay, index, len(needle)),
                    })
                    if len(matches) >= limit:
                        stopped_by = "max_matches"
                        break
                if per_file:
                    counts["files_matched"] += 1
                    tainted = tainted or self._is_spill(file)
                if stopped_by is not None:
                    break
            result = {
                "ok": True,
                "path": str(target),
                "pattern": pattern,
                "case_sensitive": case_sensitive,
                "whole_word": whole_word,
                "glob": glob,
                "matches": matches,
                "files_scanned": counts["files_scanned"],
                "files_matched": counts["files_matched"],
                "files_capped": counts["files_capped"],
                "hidden": counts["hidden"],
                "skipped": {
                    "binary": counts["binary"], "large": counts["large"],
                    "symlink": counts["symlink"],
                },
                "truncated": stopped_by is not None,
                "stopped_by": stopped_by,
            }
            if tainted:
                # A snippet of a spilled tool result is that tool's output (H661).
                result["tainted"] = True
            return result

        try:
            result = await asyncio.to_thread(_search)
        except OSError as exc:
            return {"ok": False, "reason": "io_error", "detail": exc.__class__.__name__}
        self._record(
            "file.search", f"{target}: {pattern[:120]}", ok=result.get("ok") is True,
            matches=len(result.get("matches") or ()),
        )
        return await _with_project_context(result, target)   # H594

    # ── gated (reversible by construction) ───────────────────────────────────

    async def write_file(self, args: Mapping[str, Any], *, approved: bool = False) -> dict:
        """Snapshot the previous bytes, then replace the file atomically.

        ``approved`` is set only by the ToolRPC execute path (durable approval
        already verified); a direct caller stays subject to a kernel QUEUE.
        """
        content = args.get("content")
        if not isinstance(content, str):
            return {"ok": False, "reason": "bad_content"}
        data = content.encode("utf-8")
        if len(data) > self.max_bytes:
            return {"ok": False, "reason": "too_large"}
        result = await self._mutate(args.get("path"), "write", data, approved=approved)
        if result.get("ok") is True:
            # H507: warn-only — the model reads what it just wrote that looks dangerous.
            from .code_guidance import result_fields

            try:
                result.update(result_fields(str(result.get("path") or args.get("path") or ""), content))
            except Exception:
                logger.warning("code guidance for a file write failed", exc_info=True)
        return result

    async def delete_file(self, args: Mapping[str, Any], *, approved: bool = False) -> dict:
        return await self._mutate(args.get("path"), "delete", b"", approved=approved)

    async def _mutate(self, raw_path: object, op: str, data: bytes, *, approved: bool) -> dict:
        try:
            target = self.scope.resolve(raw_path)
        except FileScopeError as exc:
            return {"ok": False, "reason": exc.reason}
        root = self.scope.root_for(target)
        if root is None or target == root:
            return {"ok": False, "reason": "outside_scope"}

        def _snapshot() -> Snapshot | str:
            if target.exists() and not target.is_file():
                return "not_a_file"
            if op == "delete" and not target.exists():
                return "not_found"
            try:
                return self.snapshots.take(target)
            except ValueError as exc:
                return str(exc) or "snapshot_failed"

        try:
            snap = await asyncio.to_thread(_snapshot)
        except OSError as exc:
            return {"ok": False, "reason": "snapshot_failed", "detail": exc.__class__.__name__}
        if isinstance(snap, str):
            return {"ok": False, "reason": snap}

        payload = {
            "kind": KIND,
            "op": op,
            "path": str(target),
            "root": str(root),
            "bytes": len(data),
            "max_bytes": self.max_bytes,
            "snapshot_ref": snap.ref,
        }
        decision = FILE_WRITE_CONTRACT.evaluate(payload, now=time.time())
        if not decision.admissible:
            reason = decision.reason or "contract_denied"
            self._record("file.contract_denied", f"{op} {target}: {reason}", ok=False)
            return {"ok": False, "reason": reason, "snapshot_ref": snap.ref}

        # H506 — does this write steer a future run? Checked on both the resolved
        # target and the name the caller spelled, because a symlink can hide one
        # behind the other in either direction (see :func:`_requested_name`).
        # Carried in the payload so the kernel decides *knowing* that.
        labels = instruction_labels(target.name, _requested_name(raw_path))
        steers = labels is not None
        payload["steers_future_runs"] = steers

        denied = self._authorize(op, target, payload, approved=approved)
        if denied is not None:
            self._record("file.kernel_denied", f"{op} {target}: {denied}", ok=False)
            return {"ok": False, "reason": denied, "snapshot_ref": snap.ref}
        # A floor on *this API surface*, for any caller that reaches write_file /
        # delete_file directly: such a call must say ``approved=True`` for an
        # instruction file, whatever the kernel says and whether or not it is on.
        # It sits after the kernel so a DENY keeps its own, more informative reason.
        #
        # Scope, plainly: the shipped ToolRPC path passes this floor by design —
        # :func:`register_file_tools`' closures run only from
        # :meth:`ToolRPCServer.execute`, i.e. only after the owner decided the card,
        # and they pass ``approved=True``. What makes the class distinct *there* is
        # the classifier: the card names the class (see
        # :meth:`FileTools.classify_mutation`) and ``execute`` refuses a call whose
        # approved card did not carry it. This floor is the belt for a future
        # in-process caller, not the braces the owner sees.
        if steers and not approved:
            self._record("file.instruction_floor", f"{op} {target}", ok=False)
            return {
                "ok": False,
                "reason": "approval_required",
                "class": INSTRUCTION_CLASS,
                "snapshot_ref": snap.ref,
            }

        def _apply() -> None:
            if op == "delete":
                target.unlink()
                return
            mode = snap.mode if snap.existed else 0o644
            _atomic_write(target, data, mode=mode)

        try:
            await asyncio.to_thread(_apply)
        except OSError as exc:
            self._record(f"file.{op}", f"{target}: io_error", ok=False)
            return {
                "ok": False, "reason": "io_error", "detail": exc.__class__.__name__,
                "snapshot_ref": snap.ref,
            }
        self._record(f"file.{op}", str(target), ok=True, snapshot_ref=snap.ref)
        return {
            "ok": True,
            "op": op,
            "path": str(target),
            "bytes": len(data),
            "existed": snap.existed,
            "snapshot_ref": snap.ref,
        }

    def _authorize(self, op: str, target: Path, payload: dict, *, approved: bool) -> str | None:
        """Ask the injected kernel hook. Returns a refusal reason or ``None``."""
        if self._authorizer is None:
            return None
        from agents.core.action_origin import current_action_origin
        from agents.core.kernel import Action, Verdict, kernel_enabled

        if not kernel_enabled():
            # Same default-off shape as ToolRPCServer._kernel_denial: the hook is
            # bound at boot but consulted only once JARVIS_ACTION_KERNEL is on.
            return None
        action = Action(
            kind=KIND, agent=self.agent, title=f"file {op} {target.name}",
            payload={
                k: payload[k]
                for k in ("op", "path", "bytes", "snapshot_ref", "steers_future_runs")
            },
            origin=current_action_origin(),
        )
        try:
            decision = self._authorizer(action)
        except Exception:
            logger.warning("file tools kernel hook failed closed", exc_info=True)
            return "kernel_error"
        verdict = getattr(decision, "verdict", None)
        if verdict is Verdict.DENY:
            reason = getattr(decision, "reason", "") or "denied"
            return f"kernel_denied:{reason}"
        if verdict is Verdict.QUEUE and not approved:
            return "approval_required"
        if verdict not in (Verdict.GRANT, Verdict.QUEUE):
            return "kernel_error"
        return None

    # ── rollback ─────────────────────────────────────────────────────────────

    def restore_snapshot(self, ref: object) -> bool:
        """Put the file back exactly as the snapshot recorded it (or remove it
        when it did not exist). Refuses unknown/tampered refs and any path that
        is no longer inside the scope. Synchronous: the manifest rollback hook
        may be called from the executor's thread."""
        if not _is_ref(ref):
            return False
        snap = self.snapshots.load(str(ref))
        if snap is None:
            return False
        try:
            target = self.scope.resolve(snap.path)
        except FileScopeError:
            self._record("file.restore", f"{snap.path}: outside_scope", ok=False)
            return False
        if str(target) != snap.path:
            return False
        try:
            if not snap.existed:
                if target.exists():
                    if not target.is_file():
                        return False
                    target.unlink()
                self._record("file.restore", str(target), ok=True, snapshot_ref=str(ref))
                return True
            data = self.snapshots.blob(snap)
            if data is None:
                return False
            if target.exists() and not target.is_file():
                return False
            _atomic_write(target, data, mode=snap.mode or 0o644)
        except OSError:
            logger.warning("file snapshot restore failed: %s", ref, exc_info=True)
            return False
        self._record("file.restore", str(target), ok=True, snapshot_ref=str(ref))
        return True

    # ── preflights (bound to this scope) ─────────────────────────────────────

    def classify_mutation(self, args: Mapping[str, Any]) -> dict[str, Any] | None:
        """H506 — the class labels for a ``file_write`` / ``file_delete`` call.

        Registered as the ToolRPC ``classifier`` for both gated tools, so it runs at
        *intake* (stamping the owner's approval card) and again at *execution*
        (where a mismatch against the approved card refuses the call). It is a pure
        look at the arguments: no bytes move, nothing is authorized here.

        Both symlink directions are covered, as in :meth:`_mutate`: the name the
        caller spelled, and — best effort, because intake must not fail on a path
        that has not been validated yet — the name it resolves to.
        """
        raw_path = (args or {}).get("path")
        names: list[object] = [_requested_name(raw_path)]
        # An unresolvable path is the preflight's refusal to make, not ours — but the
        # spelled name has already been checked, so nothing in the class slips past.
        with contextlib.suppress(FileScopeError, OSError, ValueError):
            names.append(self.scope.resolve(raw_path).name)
        classed = instruction_labels(*names)
        # H507: code-pattern warnings ride on the same card. They never set a class, so
        # the approval stays bound to what H506 classes the write as.
        content = (args or {}).get("content")
        if not isinstance(raw_path, str) or not isinstance(content, str):
            return classed
        from .code_guidance import labels as code_labels

        warned = code_labels(raw_path, content)
        if warned is None:
            return classed
        if classed is None:
            return warned
        notice = f"{classed['notice']}; {warned['notice']}"[:200]
        return {**warned, **classed, "notice": notice}

    def preflight(self, name: str) -> Callable[[dict], Mapping]:
        spec = FILE_TOOL_SPECS[name]
        shape = spec["preflight"]

        def _bound(args: dict) -> Mapping:
            clean = dict(shape(args))
            path = clean.get("path")
            if path is None and name in ("file_list", "file_search"):
                return clean
            # Only file_read has the spill door (H661); every other tool is held to
            # the owner's roots exactly as before.
            resolve = self._resolve_read if name == "file_read" else self.scope.resolve
            try:
                resolve(path)
            except FileScopeError as exc:
                raise ToolRPCValidationError(exc.reason) from None
            if name == "file_write" and len(clean["content"].encode("utf-8")) > self.max_bytes:
                raise ToolRPCValidationError("too_large")
            return clean

        return _bound

    def _record(self, action: str, why: str, **meta) -> None:
        if self._audit is None:
            return
        try:
            if hasattr(self._audit, "record"):
                self._audit.record(actor="file_tools", action=action, why=why, metadata=meta)
            elif hasattr(self._audit, "log"):
                self._audit.log({"event": action, "why": why, **meta})
        except Exception:
            logger.debug("file tools audit sink failed", exc_info=True)


def _parser_available(suffix: str) -> bool:
    import importlib.util

    module = _DOCUMENT_PARSERS.get(suffix)
    if module is None:
        return False
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _utf8_page_end(data: bytes) -> int:
    """How much of *data* to keep so a page never ends inside a UTF-8 character.

    A byte page cut through a multi-byte character decodes as a replacement mark at
    the end of one page and another at the start of the next, so a reader paging a
    perfectly good file reassembles a corrupted one. Dropping the incomplete tail
    moves those bytes to the next page instead. Never returns 0: a page too small for
    one whole character keeps the fragment rather than stall the reader at the same
    offset forever.
    """
    size = len(data)
    for back in range(1, min(4, size) + 1):
        byte = data[size - back]
        if byte & 0xC0 == 0x80:  # a continuation byte: keep looking for the lead
            continue
        if 0xF0 <= byte <= 0xF7:
            needed = 4
        elif 0xE0 <= byte <= 0xEF:
            needed = 3
        elif 0xC0 <= byte <= 0xDF:
            needed = 2
        else:
            needed = 1
        if needed > back and size - back > 0:
            return size - back
        return size
    return size


def _page(data: bytes, *, offset: int, total: int) -> dict:
    """The page fields every read shares: what was returned, and where the rest is.

    ``truncated`` keeps its meaning — more of the file follows what was returned —
    and ``next_offset`` is present exactly when it is true, so "pass next_offset back
    as offset until it is absent" reads the whole file and stops.
    """
    end = offset + len(data)
    if end < total:
        data = data[:_utf8_page_end(data)]
        end = offset + len(data)
    fields: dict[str, Any] = {
        "content": data.decode("utf-8", errors="replace"),
        "bytes": len(data),
        "offset": offset,
        "truncated": end < total,
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    if end < total:
        fields["next_offset"] = end
    return fields


def _read_document(target: Path, size: int, limit: int, offset: int = 0) -> dict:
    """The text of a .pdf / .docx, bounded like any read; a named refusal otherwise.

    ``offset`` counts bytes of the *extracted text* (UTF-8), not of the file: that is
    the text the reader was shown, so it is the only thing a page number can mean.
    ``size`` stays the file's size on disk and ``text_size`` names the text's.
    """
    suffix = target.suffix.lower()
    if not _parser_available(suffix):
        return {
            "ok": False,
            "reason": "parser_missing",
            "detail": f"reading {suffix} needs the {_DOCUMENT_PARSERS[suffix]} package; raw=true returns the bytes",
        }
    text = extract_text(target)
    if text is None:
        return {"ok": False, "reason": "extraction_failed", "detail": "the file could not be parsed"}
    data = text.encode("utf-8")
    return {
        "ok": True,
        "path": str(target),
        **_page(data[offset:offset + limit], offset=offset, total=len(data)),
        "size": size,
        "text_size": len(data),
        "extracted": True,
        "format": suffix.lstrip("."),
    }


def _walk_files(target: Path, root: Path, counts: dict[str, int]):
    """Yield ``(path, size)`` for every regular file under *target* the read tools
    would show: symlinks are never followed (counted), secret-looking names and
    directories are pruned (counted as hidden), everything else is visited in
    sorted order so a search is deterministic."""
    if target.is_file():
        yield target, target.stat().st_size
        return
    for dirpath, dirnames, filenames in os.walk(target, topdown=True, followlinks=False):
        here = Path(dirpath)
        try:
            relative = here.relative_to(root).parts
        except ValueError:
            relative = ()
        kept: list[str] = []
        for name in sorted(dirnames):
            if os.path.islink(here / name):
                counts["symlink"] += 1
            elif _has_secret_part((*relative, name)):
                counts["hidden"] += 1
            else:
                kept.append(name)
        dirnames[:] = kept
        for name in sorted(filenames):
            if looks_secret_name(name):
                counts["hidden"] += 1
                continue
            child = here / name
            try:
                info = child.lstat()
            except OSError:
                continue
            if stat.S_ISLNK(info.st_mode):
                counts["symlink"] += 1
                continue
            if not stat.S_ISREG(info.st_mode):
                continue
            yield child, int(info.st_size)


def _is_word_char(char: str) -> bool:
    return bool(char) and (char.isalnum() or char == "_")


def _find_literal(hay: str, needle: str, whole_word: bool) -> int:
    """First index of *needle* in *hay* (already case-folded by the caller), or -1;
    with *whole_word* only where neither neighbour is a word character."""
    start = 0
    while True:
        index = hay.find(needle, start)
        if index < 0 or not whole_word:
            return index
        before = hay[index - 1] if index > 0 else ""
        end = index + len(needle)
        after = hay[end] if end < len(hay) else ""
        if not _is_word_char(before) and not _is_word_char(after):
            return index
        start = index + 1


def _snippet(line: str, index: int, width: int) -> str:
    """At most ``SNIPPET_CHARS`` of *line* around the match, with ellipses where cut."""
    if len(line) <= SNIPPET_CHARS:
        return line
    index = max(0, min(index, len(line)))
    half = max(0, (SNIPPET_CHARS - min(width, SNIPPET_CHARS)) // 2)
    start = max(0, index - half)
    end = min(len(line), start + SNIPPET_CHARS)
    start = max(0, end - SNIPPET_CHARS)
    out = line[start:end]
    if start > 0:
        out = "…" + out
    if end < len(line):
        out = out + "…"
    return out


def restore_snapshot(ref: object, *, tools: FileTools | None = None) -> bool:
    """Manifest rollback hook (``handler_ref='agents.core.file_tools:restore_snapshot'``)."""
    try:
        instance = tools if tools is not None else FileTools.from_env()
    except ValueError:
        return False
    return instance.restore_snapshot(ref)


# ── tool specs (shape-only preflights; the scope is bound at registration) ──

def _path_arg(args: Mapping[str, Any], *, required: bool) -> str | None:
    path = args.get("path")
    if path is None and not required:
        return None
    if not isinstance(path, str) or not path.strip() or len(path) > MAX_PATH_CHARS:
        raise ToolRPCValidationError("bad_path")
    if "\x00" in path:
        raise ToolRPCValidationError("bad_path")
    return path.strip()


def _preflight_read(args: dict) -> Mapping:
    clean: dict[str, Any] = {"path": _path_arg(args, required=True)}
    if "max_bytes" in args:
        value = args["max_bytes"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ToolRPCValidationError("bad_max_bytes")
        clean["max_bytes"] = value
    if "raw" in args:
        if not isinstance(args["raw"], bool):
            raise ToolRPCValidationError("bad_flag")
        clean["raw"] = args["raw"]
    if "offset" in args:
        value = args["offset"]
        if not _valid_offset(value):
            raise ToolRPCValidationError("bad_offset")
        clean["offset"] = value
    return clean


def _preflight_list(args: dict) -> Mapping:
    clean: dict[str, Any] = {}
    path = _path_arg(args, required=False)
    if path is not None:
        clean["path"] = path
    if "max_entries" in args:
        value = args["max_entries"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ToolRPCValidationError("bad_max_entries")
        clean["max_entries"] = min(value, MAX_LIST_ENTRIES)
    return clean


def _preflight_search(args: dict) -> Mapping:
    pattern = args.get("pattern")
    if (
        not isinstance(pattern, str) or not pattern or len(pattern) > MAX_PATTERN_CHARS
        or "\x00" in pattern
    ):
        raise ToolRPCValidationError("bad_pattern")
    clean: dict[str, Any] = {"pattern": pattern}
    path = _path_arg(args, required=False)
    if path is not None:
        clean["path"] = path
    for flag in ("case_sensitive", "whole_word"):
        if flag in args:
            if not isinstance(args[flag], bool):
                raise ToolRPCValidationError("bad_flag")
            clean[flag] = args[flag]
    if "glob" in args:
        glob = args["glob"]
        if (
            not isinstance(glob, str) or not glob or len(glob) > MAX_GLOB_CHARS
            or "\x00" in glob or "/" in glob or "\\" in glob
        ):
            raise ToolRPCValidationError("bad_glob")
        clean["glob"] = glob
    if "max_matches" in args:
        value = args["max_matches"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ToolRPCValidationError("bad_max_matches")
        clean["max_matches"] = min(value, MAX_SEARCH_MATCHES)
    return clean


def _preflight_write(args: dict) -> Mapping:
    path = _path_arg(args, required=True)
    content = args.get("content")
    if not isinstance(content, str):
        raise ToolRPCValidationError("bad_content")
    return {"path": path, "content": content}


def _preflight_delete(args: dict) -> Mapping:
    return {"path": _path_arg(args, required=True)}


_PATH_SCHEMA = {"type": "string", "maxLength": MAX_PATH_CHARS}

FILE_TOOL_SPECS: dict[str, dict[str, Any]] = {
    "file_read": {
        "description": (
            "Read one UTF-8 file inside the owner's file roots (bounded bytes); a .pdf or "
            ".docx is returned as its extracted text (raw=true for the bytes). offset "
            "starts the read at that byte; a read that stops early returns next_offset — "
            "pass it back as offset to page through a large file or a spilled tool result."
        ),
        "gated": False,
        "trusted_execution": False,
        "capability_id": "tool:file_read",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": _PATH_SCHEMA,
                "max_bytes": {"type": "integer", "minimum": 1},
                "offset": {"type": "integer", "minimum": 0, "maximum": MAX_OFFSET},
                "raw": {"type": "boolean"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "preflight": _preflight_read,
    },
    "file_list": {
        "description": "List one directory inside the owner's file roots (bounded entries).",
        "gated": False,
        "trusted_execution": False,
        "capability_id": "tool:file_list",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": _PATH_SCHEMA,
                "max_entries": {"type": "integer", "minimum": 1, "maximum": MAX_LIST_ENTRIES},
            },
            "additionalProperties": False,
        },
        "preflight": _preflight_list,
    },
    "file_search": {
        "description": (
            "Search file contents inside the owner's file roots for a literal phrase "
            "(not a regex; case-insensitive unless case_sensitive). Returns bounded "
            "snippets with path and line; says when a cap stopped the search."
        ),
        "gated": False,
        "trusted_execution": False,
        "capability_id": "tool:file_search",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "minLength": 1, "maxLength": MAX_PATTERN_CHARS},
                "path": _PATH_SCHEMA,
                "glob": {"type": "string", "minLength": 1, "maxLength": MAX_GLOB_CHARS},
                "case_sensitive": {"type": "boolean"},
                "whole_word": {"type": "boolean"},
                "max_matches": {"type": "integer", "minimum": 1, "maximum": MAX_SEARCH_MATCHES},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
        "preflight": _preflight_search,
    },
    "file_write": {
        "description": (
            "Propose replacing one file's contents inside the owner's file roots; "
            "runs only after approval, with the previous bytes snapshotted for restore. "
            "A file that steers a future run (SOUL.md, AGENTS.md, CLAUDE.md, ...) is "
            "asked as its own class and the owner is told so."
        ),
        "gated": True,
        "trusted_execution": True,
        "capability_id": "tool:file_write",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": _PATH_SCHEMA,
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        "preflight": _preflight_write,
    },
    "file_delete": {
        "description": (
            "Propose deleting one file inside the owner's file roots; runs only after "
            "approval, with the bytes snapshotted for restore. Deleting a file that "
            "steers a future run is asked as its own class."
        ),
        "gated": True,
        "trusted_execution": True,
        "capability_id": "tool:file_delete",
        "input_schema": {
            "type": "object",
            "properties": {"path": _PATH_SCHEMA},
            "required": ["path"],
            "additionalProperties": False,
        },
        "preflight": _preflight_delete,
    },
}

GATED_TOOL_KINDS = tuple(
    f"toolrpc.{name}" for name, spec in FILE_TOOL_SPECS.items() if spec["gated"]
)


def file_tools_enabled() -> bool:
    return env_flag(FLAG)


def register_file_tools(
    server: Any,
    tools: FileTools | None = None,
    *,
    enabled: bool | None = None,
) -> list[str]:
    """Register the five file tools on a ToolRPC server. Default-off: returns
    ``[]`` without touching the server unless ``JARVIS_FILE_TOOLS`` is on (or
    ``enabled=True`` is passed explicitly)."""
    on = file_tools_enabled() if enabled is None else bool(enabled)
    if not on:
        return []
    instance = tools if tools is not None else FileTools.from_env()

    async def _read(args: dict) -> dict:
        return await instance.read_file(args)

    async def _list(args: dict) -> dict:
        return await instance.list_dir(args)

    async def _search(args: dict) -> dict:
        return await instance.search_files(args)

    async def _write(args: dict) -> dict:
        # Reached only through ToolRPCServer.execute after durable approval
        # (gated tools never run inline from handle()), and only after that
        # execute matched the call's H506 class against the approved card.
        return await instance.write_file(args, approved=True)

    async def _delete(args: dict) -> dict:
        return await instance.delete_file(args, approved=True)

    def _classify(args: dict) -> Mapping[str, Any] | None:
        # H506 — server-owned, registered here, never selectable by call data: a
        # sandboxed script cannot label its own write, nor strip the label off one.
        return instance.classify_mutation(args)

    handlers = {
        "file_read": _read, "file_list": _list, "file_search": _search,
        "file_write": _write, "file_delete": _delete,
    }
    classifiers: dict[str, Callable[[dict], Mapping[str, Any] | None]] = {
        "file_write": _classify, "file_delete": _classify,
    }
    registered: list[str] = []
    for name, spec in FILE_TOOL_SPECS.items():
        server.register_tool(
            name,
            handlers[name],
            gated=spec["gated"],
            description=spec["description"],
            input_schema=spec["input_schema"],
            capability_id=spec["capability_id"],
            preflight=instance.preflight(name),
            trusted_execution=spec["trusted_execution"],
            classifier=classifiers.get(name),
        )
        registered.append(name)
    return registered


__all__ = [
    "KIND", "FLAG", "ROOTS_ENV", "MAX_BYTES_ENV", "DEFAULT_MAX_BYTES", "MAX_OFFSET",
    "FILE_WRITE_CONTRACT", "FILE_TOOL_SPECS", "GATED_TOOL_KINDS",
    "FileScope", "FileScopeError", "FileTools", "Snapshot", "SnapshotStore",
    "SECRET_NAME_TOKENS", "looks_secret_name", "restore_snapshot", "register_file_tools",
    "INSTRUCTION_BASE_NAMES", "INSTRUCTION_FILE_NAMES", "INSTRUCTION_FILE_SUFFIXES",
    "INSTRUCTION_CLASS", "INSTRUCTION_NOTICE",
    "looks_instruction_name", "instruction_labels",
    "file_tools_enabled",
]
