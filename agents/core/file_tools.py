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
* Default-off: :func:`register_file_tools` is a no-op unless
  ``JARVIS_FILE_TOOLS`` is set. Roots come from ``JARVIS_FILE_ROOTS``
  (default ``data_path('workspace')``); the byte cap from
  ``JARVIS_FILE_MAX_BYTES`` (default 2 000 000).
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

from agents.core.automation_contracts import ContractTemplate, predicate
from agents.core.env_config import env_flag, env_int, env_list
from agents.core.environments import SECRET_ENV_SUBSTRINGS
from agents.core.local_docs import DOC_EXTS, extract_text
from agents.core.paths import data_path
from agents.core.tool_rpc import ToolRPCValidationError

logger = logging.getLogger("jarvis.file_tools")

# ── vocabulary ───────────────────────────────────────────────────────────────

KIND = "file.write"
FLAG = "JARVIS_FILE_TOOLS"
ROOTS_ENV = "JARVIS_FILE_ROOTS"
MAX_BYTES_ENV = "JARVIS_FILE_MAX_BYTES"
DEFAULT_MAX_BYTES = 2_000_000
MAX_PATH_CHARS = 4096
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

    @classmethod
    def from_env(cls, *, authorizer: Callable[..., Any] | None = None, audit: Any = None) -> FileTools:
        return cls(FileScope.from_env(), authorizer=authorizer, audit=audit)

    # ── ungated ──────────────────────────────────────────────────────────────

    async def read_file(self, args: Mapping[str, Any]) -> dict:
        try:
            target = self.scope.resolve(args.get("path"))
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
                return _read_document(target, size, limit)
            with target.open("rb") as handle:
                data = handle.read(limit)
            return {
                "ok": True,
                "path": str(target),
                "content": data.decode("utf-8", errors="replace"),
                "bytes": len(data),
                "size": size,
                "truncated": size > len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }

        try:
            result = await asyncio.to_thread(_read)
        except OSError as exc:
            return {"ok": False, "reason": "io_error", "detail": exc.__class__.__name__}
        self._record("file.read", str(target), ok=result.get("ok") is True)
        return result

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
        return result

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
                if stopped_by is not None:
                    break
            return {
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

        try:
            result = await asyncio.to_thread(_search)
        except OSError as exc:
            return {"ok": False, "reason": "io_error", "detail": exc.__class__.__name__}
        self._record(
            "file.search", f"{target}: {pattern[:120]}", ok=result.get("ok") is True,
            matches=len(result.get("matches") or ()),
        )
        return result

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
        return await self._mutate(args.get("path"), "write", data, approved=approved)

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

        denied = self._authorize(op, target, payload, approved=approved)
        if denied is not None:
            self._record("file.kernel_denied", f"{op} {target}: {denied}", ok=False)
            return {"ok": False, "reason": denied, "snapshot_ref": snap.ref}

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
            payload={k: payload[k] for k in ("op", "path", "bytes", "snapshot_ref")},
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

    def preflight(self, name: str) -> Callable[[dict], Mapping]:
        spec = FILE_TOOL_SPECS[name]
        shape = spec["preflight"]

        def _bound(args: dict) -> Mapping:
            clean = dict(shape(args))
            path = clean.get("path")
            if path is None and name in ("file_list", "file_search"):
                return clean
            try:
                self.scope.resolve(path)
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


def _read_document(target: Path, size: int, limit: int) -> dict:
    """The text of a .pdf / .docx, bounded like any read; a named refusal otherwise."""
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
    shown = data[:limit]
    return {
        "ok": True,
        "path": str(target),
        "content": shown.decode("utf-8", errors="ignore"),
        "bytes": len(shown),
        "size": size,
        "extracted": True,
        "format": suffix.lstrip("."),
        "truncated": len(data) > len(shown),
        "sha256": hashlib.sha256(shown).hexdigest(),
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
            ".docx is returned as its extracted text (raw=true for the bytes)."
        ),
        "gated": False,
        "trusted_execution": False,
        "capability_id": "tool:file_read",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": _PATH_SCHEMA,
                "max_bytes": {"type": "integer", "minimum": 1},
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
            "runs only after approval, with the previous bytes snapshotted for restore."
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
            "approval, with the bytes snapshotted for restore."
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
        # (gated tools never run inline from handle()).
        return await instance.write_file(args, approved=True)

    async def _delete(args: dict) -> dict:
        return await instance.delete_file(args, approved=True)

    handlers = {
        "file_read": _read, "file_list": _list, "file_search": _search,
        "file_write": _write, "file_delete": _delete,
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
        )
        registered.append(name)
    return registered


__all__ = [
    "KIND", "FLAG", "ROOTS_ENV", "MAX_BYTES_ENV", "DEFAULT_MAX_BYTES",
    "FILE_WRITE_CONTRACT", "FILE_TOOL_SPECS", "GATED_TOOL_KINDS",
    "FileScope", "FileScopeError", "FileTools", "Snapshot", "SnapshotStore",
    "SECRET_NAME_TOKENS", "looks_secret_name", "restore_snapshot", "register_file_tools",
    "file_tools_enabled",
]
