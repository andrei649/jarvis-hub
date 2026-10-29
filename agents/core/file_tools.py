"""file_tools.py — governed file tools reachable from the model loop (H20.R1).

Productivity work is mostly files, so the model-directed tool loop gets five
tools that are *governed by construction*:

  * ``file_read`` / ``file_list`` / ``file_search`` — ungated, but only inside
    the owner's :class:`FileScope` (resolved roots, no ``..`` traversal, no
    symlink escape, no secret-looking names) and bounded in bytes / entries /
    matches. ``file_search`` (Hermes absorption 3a) is a *literal* search by
    default, linear by construction. H303 added ``regex: true`` and a glob
    file-finding mode on the same containment: the file set always comes from
    :func:`_walk_files` (the read tools' rules), never from a tool walking the
    disk on its own. A regex is Python ``re`` syntax and semantics, run by ONE
    engine: a child Python process that is killed at the deadline
    (:func:`_py_regex_scan`) — ``re`` backtracks without bound on patterns no
    static check can list, so the only guarantee is a process the parent can kill.
    Ripgrep is deliberately not used for regex search: its Unicode classes
    (``\\w \\b \\s``) differ from Python's, so the rows would depend on whether it is
    installed, and its JSON output grows with the number of matches in a line
    (``\\w`` on a 2 MB line is gigabytes), which the parent cannot bound. Lines are
    matched whole, a file that is not UTF-8 is decoded with replacement
    characters, a nested unbounded repeat is refused (``regex_too_complex``,
    :func:`_regex_too_complex`) and so is a construct whose meaning depends on the
    regex flavour (``bad_regex``, :func:`_portability_error`). Dependency
    and build trees (:data:`NOISE_DIRS`, plain ``.gitignore`` directory names) are
    pruned unless ``include_ignored``; a glob may use ``{a,b}`` and a leading ``!``.
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
* H444 — ``file_read`` also pages by whole lines (``line_offset`` / ``line_limit`` →
  ``next_line_offset``, bounded by ``max_bytes``; :func:`_line_page`). A .pdf / .docx
  is read once into memory within the 50 MB ceiling and parsed from those bytes, never
  the path (:func:`_admitted_bytes`); the parse is cached under their SHA-256
  (:class:`DocumentCache`), so later pages of an unchanged document are not parsed
  again (a stop on the load-dependent time budget is not cached). Extraction is
  budgeted (``extraction_incomplete``), and garbled pages and pages holding images
  are named beside the text (no OCR is performed). A .docx is walked in document
  order — tables, text boxes, headers/footers, notes — and its images, charts and
  equations are named (:func:`_docx_annotations`).
* H303 — a line window can be *numbered* (``line_numbers: true`` prefixes each line
  with its 1-based number, ``cat -n`` style) and *capped* per line (``max_line_chars``:
  a longer line is cut to that many characters plus :data:`LINE_CUT_MARKER`, still
  counted as one line, so one minified bundle line no longer fills a page by itself
  and ``next_line_offset`` stays exact). Numbered output caps at
  :data:`DEFAULT_LINE_CHARS` unless told otherwise; a plain window keeps H444's
  uncapped lines. ``file_search`` gained ``regex: true`` and a glob file-finding mode
  (``glob`` without ``pattern``) — see the first bullet.
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
import io
import json
import logging
import os
import re
import stat
import subprocess  # nosec B404 - fixed argv, no shell, explicit files only
import sys
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.core import project_context
from agents.core.automation_contracts import ContractTemplate, predicate
from agents.core.env_config import env_flag, env_int, env_list
from agents.core.environments import SECRET_ENV_SUBSTRINGS
from agents.core.local_docs import (
    DOC_EXTS,
    DOCX_READ_KINDS,
    DOCX_VISUAL_KINDS,
    DocumentExtraction,
    extract_docx_document,
    extract_pdf_document,
    page_ranges,
    pdf_coverage_warning,
)
from agents.core.paths import data_path
from agents.core.tool_result_store import SPILL_DIRNAME as _SPILL_DIRNAME
from agents.core.tool_result_store import is_reference as _is_spill_reference
from agents.core.tool_rpc import (
    MAX_IMAGE_BYTES,
    ToolContent,
    ToolRPCValidationError,
    current_tool_turn,
    image_signature_ok,
)

logger = logging.getLogger("jarvis.file_tools")

# ── vocabulary ───────────────────────────────────────────────────────────────

KIND = "file.write"
FLAG = "JARVIS_FILE_TOOLS"
ROOTS_ENV = "JARVIS_FILE_ROOTS"
MAX_BYTES_ENV = "JARVIS_FILE_MAX_BYTES"
DEFAULT_MAX_BYTES = 2_000_000
MAX_DOCUMENT_BYTES = 50_000_000
MAX_PATH_CHARS = 4096
#: H444 — ``file_read``'s line window: ``line_offset`` (1-based first line) and
#: ``line_limit`` (lines per page, default :data:`DEFAULT_LINE_LIMIT`). The window
#: is still bounded by ``max_bytes``.
DEFAULT_LINE_LIMIT = 500
MAX_LINE_LIMIT = 2000
#: H303 — the per-line cap of a line window (``max_line_chars``, in characters, the
#: newline aside). A longer line is cut to the cap and ends with :data:`LINE_CUT_MARKER`
#: naming how many characters were dropped; the paging does not change (a cut line is
#: still one line). Numbered output (``line_numbers``) caps at :data:`DEFAULT_LINE_CHARS`
#: unless ``max_line_chars`` says otherwise; a plain window has no cap unless asked.
DEFAULT_LINE_CHARS = 2000
MIN_LINE_CHARS = 8
MAX_LINE_CHARS = 100_000
LINE_CUT_MARKER = " …[+{more} chars]"
#: H444 — parsed documents a :class:`FileTools` keeps, keyed by the SHA-256 of the
#: admitted input bytes, so paging a document does not parse it again.
DOCUMENT_CACHE_ENTRIES = 8
DOCUMENT_CACHE_TEXT_BYTES = 64_000_000
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
# H297 — an image inside the roots is read as the image itself: a ToolContent result
# (a one-line summary plus the image part), which a model whose tool results carry
# images sees as a picture and any other model reads as its descriptor. Bytes that do
# not carry their suffix's signature are not an image and page like any other file;
# ``raw=true`` (or an offset) always returns bytes.
IMAGE_SUFFIXES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp",
}
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
#: H303 — one regex child process searches at most this many files / bytes of files. The
#: child writes at most ``MAX_MATCHES_PER_FILE`` snippets per file, so its output is
#: bounded by the batch (never by how many matches a line holds), and the files it is
#: given are explicit paths from :func:`_walk_files`.
REGEX_BATCH_FILES = 128
REGEX_BATCH_BYTES = 4_000_000
_UTF8_CONTINUATION = bytes(range(0x80, 0xC0))
#: H303 — regular files a search may *visit* (:data:`MAX_WALK_FILES`) and directory
#: entries it may *examine* (:data:`MAX_WALK_ENTRIES`: every file, directory, symlink and
#: secret-looking name the walk meets, matched or not). A glob search is not held to
#: :data:`MAX_SEARCH_FILES`, which counts files whose contents were searched, so files
#: that do not match never use up the budget that later directories need; and because
#: secret names and symlinks are examined but never yielded, only the entry cap and the
#: deadline (checked inside the walk) stop a tree made of them.
MAX_WALK_FILES = 100_000
MAX_WALK_ENTRIES = 200_000
#: H303 — directories a content or glob search does not descend into unless asked
#: (``include_ignored: true``): dependency, build and cache trees that hold thousands of
#: files nobody searches for, and that a code search tool skips by convention. The
#: count of pruned directories is reported as ``ignored``. ``.git`` is a secret path
#: (``hidden``). A ``path`` that is itself one of them is searched: only what lies
#: *below* the searched directory is pruned.
NOISE_DIRS = frozenset({
    "node_modules", "venv", ".venv", "__pycache__", "dist", "build", "target", ".tox",
    ".nox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
})
MAX_GITIGNORE_BYTES = 65536
#: H303 — most alternatives a brace glob (``*.{py,md}``) may expand to.
MAX_GLOB_ALTERNATIVES = 32

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

def _without_workspace_data(setting: str, roots: list[str]) -> list[str]:
    """*roots* minus any that reaches the Nerva Workspace's company data (NWS-17).

    The workspace module is imported only when roots are configured, so the default path
    never loads it; its guard keeps every other root unchanged and in order.
    """
    if not roots:
        return roots
    from agents.core.workspace import config as workspace_config

    return workspace_config.hub_roots_without_workspace(setting, roots)


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
        """``JARVIS_FILE_ROOTS``, else ``data_path('workspace')``.

        A configured root that is, contains or lies inside the Nerva Workspace data
        directory (company data) is dropped with one warning, and when none is left the
        default applies (:func:`_without_workspace_data`, BACKLOG NWS-17).
        """
        roots = _without_workspace_data(ROOTS_ENV, env_list(ROOTS_ENV))
        return cls(roots or [str(data_path("workspace"))])

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
        return self.take_captured(target, existed=existed, data=data, mode=mode, now=now)

    def take_captured(self, target: Path, *, existed: bool, data: bytes,
                      mode: int, now: float | None = None) -> Snapshot:
        """Persist bytes already read through a scoped file descriptor.

        The pre-undo path uses this rather than opening the name a second time.
        Its record/blob format is exactly the existing SnapshotStore format.
        """
        if not isinstance(data, bytes) or not isinstance(existed, bool):
            raise ValueError("invalid captured snapshot")
        if not existed and (data or mode):
            raise ValueError("invalid absent snapshot")
        from .file_checkpoint_history import HISTORY_SUPPORTED, _locked

        if HISTORY_SUPPORTED:
            with _locked(self._dir):
                return self._persist_captured(target, existed=existed, data=data,
                                              mode=mode, now=now)
        return self._persist_captured(target, existed=existed, data=data,
                                      mode=mode, now=now)

    def _persist_captured(self, target: Path, *, existed: bool, data: bytes,
                          mode: int, now: float | None) -> Snapshot:
        sha = hashlib.sha256(data).hexdigest()
        snap = Snapshot(
            path=str(target), existed=existed, blob_sha=sha, size=len(data),
            mode=mode, created_at=float(time.time() if now is None else now),
        )
        self._dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        blobs = self._dir / "blobs"
        blobs.mkdir(parents=True, exist_ok=True, mode=0o700)
        blob = self._blob_path(sha)
        if not blob.exists():
            _atomic_write(blob, data, mode=0o600)
        # Capture already knows the exact size. A corrupt existing blob must
        # not expand a bounded preimage into an unbounded verification read.
        fd = os.open(blob, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_NONBLOCK", 0))
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size != len(data):
                raise OSError("snapshot verification failed")
            with os.fdopen(os.dup(fd), "rb") as handle:
                if handle.read(len(data) + 1) != data:
                    raise OSError("snapshot verification failed")
        finally:
            os.close(fd)
        _atomic_write(self._record_path(snap.ref), snap.canonical().encode("utf-8"), mode=0o600)
        if self.load(snap.ref) is None:
            raise OSError("snapshot verification failed")
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
        if hasattr(os, "O_DIRECTORY"):
            directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
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


def _mutation_result(result: dict, target: Path, op: str, outcome: str, *,
                     attempt_id: str | None = None, verified: bool = False,
                     record: bool = True) -> dict:
    """Preserve legacy fields and add this resolved attempt's limited observation.

    Refused means the byte effect was never entered; applied means it returned,
    without read-back; unknown covers an effect whose outcome is uncertain.
    Cancellation and escaping errors return no receipt. A ToolRPC-scrubbed path
    is not a stable identity.
    """
    if attempt_id is not None and record:
        from .turn_outcome import record_file_mutation_result
        record_file_mutation_result(
            hashlib.sha256(str(target).encode('utf-8')).hexdigest(), op,
            'verified' if verified else ('applied_unverified' if outcome == 'applied' else outcome),
            attempt_id)
    return {
        **result,
        "mutation_receipt": {"path": str(target), "op": op, "outcome": outcome},
    }


async def _with_project_context(result: dict, target: Path) -> dict:
    """H594 — a read tool's result carries the convention files of *target*'s directory
    chain the turn has not been given (tainted, so the loop fences it); off the loop. A
    script's call (no tool turn) gets none: the model sees only what the script prints, so
    the files stay due for the model's own reads."""
    if project_context.current() is None or current_tool_turn() is None:
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
        # Private storage/effect primitive. Owner-facing rollback still requires a
        # separately mediated command; this is not registered as a ToolRPC tool.
        from .file_checkpoint_history import FileCheckpointHistory

        self.history = FileCheckpointHistory(self.snapshots, self.scope)
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
        self._documents = DocumentCache()

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
        line_format = _line_format_args(args)
        if isinstance(line_format, str):
            return {"ok": False, "reason": line_format}
        window = _line_window_args(args)
        if isinstance(window, str):
            return {"ok": False, "reason": window}
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
                return _read_document(target, size, limit, offset, cache=self._documents,
                                      window=window, line_format=line_format)
            if window is not None:
                with target.open("rb") as handle:
                    page = {"ok": True, "path": str(target),
                            **_line_page(handle, *window, budget=limit, **line_format),
                            "size": size}
                if self._is_spill(target):
                    page["tainted"] = True
                return page
            if not raw and offset == 0 and target.suffix.lower() in IMAGE_SUFFIXES:
                image = _read_image(target, size)
                if image is not None:
                    return image
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
        if isinstance(result, ToolContent):
            self._record("file.read", str(target), ok=True)
            result.structured = await _with_project_context(result.structured, target)
            return result
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
        """Find lines containing *pattern* under *path* (a directory, or one file) —
        or, with ``glob`` and no ``pattern``, find files by name (H303).

        A scan with the read tools' containment and nothing more: it never follows a
        symlink, skips every secret-looking name (counted as ``hidden``), reads only
        regular files under the byte cap, skips binaries (a NUL in the first 8 KiB)
        and returns a bounded snippet rather than the line. Matches, matches per file,
        files searched, files visited and wall-clock seconds are all capped; a search
        that hit a cap says ``truncated`` and names the cap in ``stopped_by`` instead
        of pretending the workspace ended there. Dependency and build trees
        (:data:`NOISE_DIRS`, plain directory names in the root's ``.gitignore``) are
        not entered unless ``include_ignored`` is true; ``ignored`` counts them.

        ``mode`` names what ran: ``literal`` (the default, linear by construction,
        each line matched on its first 8 KiB), ``regex`` (``regex: true``, each line
        matched whole) or ``glob`` (files matching ``glob`` under ``path``, listed with
        their size and not read, so the byte cap does not apply, and bounded by
        :data:`MAX_WALK_FILES` visited files rather than by files searched).

        A regex is Python ``re`` syntax and semantics and runs in a killable Python
        child process (:func:`_py_regex_scan`) over batches of the walk's own files —
        the only engine, so what a pattern matches never depends on what is installed.
        An invalid or flavour-dependent pattern is ``bad_regex``, a nested unbounded
        repeat ``regex_too_complex``; lines are matched whole and split on ``\\n``
        only, and a file that is not valid UTF-8 is decoded with replacement
        characters. A pattern Python's ``re`` cannot finish before the deadline stops
        the search with ``stopped_by: "deadline"`` and the rows found so far.
        ``files_scanned`` counts files consumed up to the one that reached a cap; on a
        deadline stop it counts only files whose search finished.

        A glob (``*``, ``?``, ``[seq]``, ``{a,b}`` alternation, a leading ``!`` to
        negate) without a ``/`` is matched against the file name, one with a ``/``
        against the path relative to ``path``; ``*`` crosses directories.
        """
        try:
            clean = _preflight_search(dict(args))
        except ToolRPCValidationError as exc:
            refusal: dict[str, Any] = {"ok": False, "reason": exc.reason}
            if exc.reason == "bad_regex":
                refusal["detail"] = _regex_error(args.get("pattern"))
            return refusal
        raw_path = clean.get("path")
        if raw_path is None:
            raw_path = str(self.scope.roots[0])
        try:
            target = self.scope.resolve(raw_path)
        except FileScopeError as exc:
            return {"ok": False, "reason": exc.reason}
        pattern = clean.get("pattern")
        case_sensitive = bool(clean.get("case_sensitive", False))
        whole_word = bool(clean.get("whole_word", False))
        glob = clean.get("glob")
        regex = bool(clean.get("regex", False))
        mode = "glob" if pattern is None else "regex" if regex else "literal"
        limit = _bounded_int(
            clean.get("max_matches"), DEFAULT_SEARCH_MATCHES,
            minimum=1, maximum=MAX_SEARCH_MATCHES,
        )
        regex_source = ""
        if mode == "regex":
            try:
                _compile_regex(pattern, case_sensitive=case_sensitive, whole_word=whole_word)
            except re.error as exc:
                return {"ok": False, "reason": "bad_regex", "detail": str(exc)[:200]}
            regex_source = _regex_source(pattern, whole_word)
        compiled_glob = _compile_glob(glob) if glob is not None else None
        include_ignored = bool(clean.get("include_ignored", False))
        needle = pattern if case_sensitive or pattern is None else pattern.lower()
        root = self.scope.root_for(target) or target
        deadline = time.monotonic() + MAX_SEARCH_SECONDS
        max_bytes = self.max_bytes
        skip_dirs: frozenset[str] = frozenset()
        skip_rooted: frozenset[str] = frozenset()
        if not include_ignored:
            ignored_any, skip_rooted = _gitignore_dirs(root)
            skip_dirs = NOISE_DIRS | ignored_any

        def _scan_literal(file: Path, data: bytes) -> tuple[list[dict], bool]:
            """Literal matches in one file's bytes, and whether its per-file cap was hit.
            Each line is matched on its first :data:`MATCH_LINE_CHARS` characters."""
            rows: list[dict] = []
            for lineno, line in enumerate(_text_lines(data.decode("utf-8", errors="replace")), 1):
                hay = line[:MATCH_LINE_CHARS]
                index = _find_literal(hay if case_sensitive else hay.lower(), needle, whole_word)
                if index < 0:
                    continue
                if len(rows) >= MAX_MATCHES_PER_FILE:
                    return rows, True
                rows.append({"path": str(file), "line": lineno, "text": _snippet(hay, index, len(needle))})
            return rows, False

        def _search() -> dict:
            if not target.exists():
                return {"ok": False, "reason": "not_found"}
            if not (target.is_file() or target.is_dir()):
                return {"ok": False, "reason": "not_a_file"}
            matches: list[dict] = []
            files: list[dict] = []
            tainted = False
            counts = {
                "files_scanned": 0, "files_matched": 0, "files_capped": 0, "hidden": 0,
                "binary": 0, "large": 0, "symlink": 0, "ignored": 0, "visited": 0,
                "entries": 0,
            }
            stopped_by: str | None = None
            unavailable = False
            #: Regex files waiting for the child process: ``(file, size)``.
            batch: list[tuple[Path, int]] = []
            batch_bytes = 0

            def _take(rows: list[dict], capped: bool, file: Path) -> bool:
                """Fold one file's rows into the result; True once the global limit is
                reached (``stopped_by`` then names it)."""
                nonlocal stopped_by, tainted
                if capped:
                    counts["files_capped"] += 1
                if rows:
                    counts["files_matched"] += 1
                    tainted = tainted or self._is_spill(file)
                for row in rows:
                    matches.append(row)
                    if len(matches) >= limit:
                        stopped_by = "max_matches"
                        return True
                return False

            def _flush() -> None:
                """Search the pending regex batch in the killable child and fold its files,
                in walk order, into the result. A batch cut by the deadline keeps the rows
                of the files finished before the kill and counts only those."""
                nonlocal stopped_by, batch, batch_bytes, unavailable
                pending, batch, batch_bytes = batch, [], 0
                if not pending or stopped_by == "max_matches":
                    return
                answer = _py_regex_scan([file for file, _ in pending], regex_source,
                                        ignore_case=not case_sensitive, deadline=deadline,
                                        max_bytes=max_bytes)
                if answer is None:
                    unavailable = True
                    return
                found, timed_out = answer
                for file, _ in pending:
                    if timed_out and file not in found:
                        continue    # cut by the deadline before it was searched: not counted
                    counts["files_scanned"] += 1
                    rows, capped = found.get(file, ([], False))
                    if _take(rows, capped, file):
                        return
                if timed_out:
                    stopped_by = "deadline"

            for file, size in _walk_files(target, root, counts, skip_dirs=skip_dirs,
                                          skip_rooted=skip_rooted, deadline=deadline,
                                          max_entries=MAX_WALK_ENTRIES):
                if time.monotonic() > deadline:
                    stopped_by = "deadline"
                    break
                counts["visited"] += 1
                if counts["visited"] > MAX_WALK_FILES or (
                        mode != "glob"
                        and counts["files_scanned"] + len(batch) >= MAX_SEARCH_FILES):
                    stopped_by = "max_files"
                    break
                if mode == "glob":
                    counts["files_scanned"] += 1      # a glob search "scans" what it visits
                    if not _glob_matches(file, target, compiled_glob):
                        continue
                    counts["files_matched"] += 1
                    files.append({"path": str(file), "size": size})
                    if len(files) >= limit:
                        stopped_by = "max_matches"
                        break
                    continue
                if compiled_glob is not None and not _glob_matches(file, target, compiled_glob):
                    continue
                if size > max_bytes:
                    counts["large"] += 1
                    continue
                with file.open("rb") as handle:
                    probe = handle.read(_BINARY_PROBE_BYTES)
                    if b"\x00" in probe:
                        counts["binary"] += 1
                        continue
                    # A regex search leaves the file to the child; a literal one reads it here.
                    data = b"" if mode == "regex" else probe + handle.read(
                        max(0, max_bytes - len(probe)))
                if mode == "regex":
                    batch.append((file, size))
                    batch_bytes += min(size, max_bytes)
                    if len(batch) >= REGEX_BATCH_FILES or batch_bytes >= REGEX_BATCH_BYTES:
                        _flush()
                else:
                    counts["files_scanned"] += 1
                    _take(*_scan_literal(file, data), file)
                if stopped_by is not None or unavailable:
                    break
            walk_stop = counts.get("walk_stopped")
            if walk_stop is not None and stopped_by is None:
                stopped_by = walk_stop        # the walk itself ran out of entries or time
            if mode == "regex" and not unavailable and stopped_by in (None, "max_files"):
                # A walk that ended (or hit the file cap) still owes the pending batch.
                _flush()
            if unavailable:
                return {
                    "ok": False, "reason": "regex_unavailable",
                    "detail": "regex search runs in a Python child process and none can be "
                              "started in this build; search a literal phrase instead",
                }
            result: dict[str, Any] = {
                "ok": True,
                "path": str(target),
                "mode": mode,
                "pattern": pattern,
                "regex": mode == "regex",
                "case_sensitive": case_sensitive,
                "whole_word": whole_word,
                "glob": glob,
            }
            if mode == "glob":
                result["files"] = files
            else:
                result["matches"] = matches
            if mode == "regex":
                result["engine"] = "python"
            result.update({
                "files_scanned": counts["files_scanned"],
                "files_matched": counts["files_matched"],
                "files_capped": counts["files_capped"],
                "hidden": counts["hidden"],
                "ignored": counts["ignored"],
                "include_ignored": include_ignored,
                "skipped": {
                    "binary": counts["binary"], "large": counts["large"],
                    "symlink": counts["symlink"],
                },
                "truncated": stopped_by is not None,
                "stopped_by": stopped_by,
            })
            if tainted:
                # A snippet of a spilled tool result is that tool's output (H661).
                result["tainted"] = True
            return result

        try:
            result = await asyncio.to_thread(_search)
        except OSError as exc:
            return {"ok": False, "reason": "io_error", "detail": exc.__class__.__name__}
        what = (f"glob {glob}" if mode == "glob" else f"regex {pattern[:120]}" if mode == "regex"
                else pattern[:120])
        self._record(
            "file.search", f"{target}: {what}", ok=result.get("ok") is True,
            matches=len(result.get("matches") or result.get("files") or ()),
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
        attempt_id: str | None = None
        target_key = hashlib.sha256(str(target).encode('utf-8')).hexdigest()
        reported: list[bool] = []

        def _result(result: dict, path: Path, operation: str, outcome: str, *,
                    verified: bool = False) -> dict:
            return _mutation_result(result, path, operation, outcome,
                                    attempt_id=attempt_id or uuid.uuid4().hex, verified=verified,
                                    record=not reported)

        from .file_checkpoint_history import (
            HISTORY_SUPPORTED,
            CapturedPreimage,
            CheckpointRefusal,
        )

        def _snapshot() -> Snapshot | CapturedPreimage | str:
            try:
                if HISTORY_SUPPORTED:
                    return self.history.capture_preimage(target, root, op=op)
                # Windows has no dirfd/no-follow effect path in this first
                # H011 unit. Preserve ordinary governed FileTools behavior,
                # explicitly leaving searchable history unsupported there.
                if target.exists() and not target.is_file():
                    return "not_a_file"
                if op == "delete" and not target.exists():
                    return "not_found"
                return self.snapshots.take(target)
            except CheckpointRefusal as exc:
                return exc.reason
            except ValueError as exc:
                return str(exc) or "snapshot_failed"

        try:
            captured = await asyncio.to_thread(_snapshot)
        except OSError as exc:
            return _result(
                {"ok": False, "reason": "snapshot_failed", "detail": exc.__class__.__name__},
                target, op, "refused",
            )
        if isinstance(captured, str):
            return _result({"ok": False, "reason": captured}, target, op, "refused")
        identity = (captured.root_dev, captured.root_ino) if isinstance(
            captured, CapturedPreimage
        ) else None
        snap = captured.snapshot if isinstance(captured, CapturedPreimage) else captured

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
            return _result(
                {"ok": False, "reason": reason, "snapshot_ref": snap.ref},
                target, op, "refused",
            )

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
            return _result(
                {"ok": False, "reason": denied, "snapshot_ref": snap.ref},
                target, op, "refused",
            )
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
            return _result({
                "ok": False,
                "reason": "approval_required",
                "class": INSTRUCTION_CLASS,
                "snapshot_ref": snap.ref,
            }, target, op, "refused")

        # The distinct physical attempt begins only after the existing contract,
        # Kernel and approval fences passed; the history worker rechecks scope
        # again at its no-follow effect boundary.
        attempt_id = uuid.uuid4().hex
        try:
            if HISTORY_SUPPORTED:
                from .turn_outcome import record_file_mutation_result

                verification: list[bool] = []
                def observed(outcome):
                    reported.append(True)
                    record_file_mutation_result(target_key, op, outcome, attempt_id)

                await asyncio.to_thread(self.history.apply_mutation, target, root, snap, op, data,
                                        expected_root=identity,
                                        tool_turn=current_tool_turn(),
                                        verification=verification,
                                        observed=observed)
            else:
                def _legacy_apply() -> None:
                    if op == "delete":
                        target.unlink()
                    else:
                        _atomic_write(target, data, mode=snap.mode if snap.existed else 0o644)

                await asyncio.to_thread(_legacy_apply)
        except FileScopeError as exc:
            # Scope resolution in apply_mutation precedes its byte effect.
            return _result(
                {"ok": False, "reason": exc.reason, "snapshot_ref": snap.ref},
                target, op, "refused",
            )
        except Exception as exc:
            if isinstance(exc, CheckpointRefusal):
                # These exact fences run before effect_started. Its other
                # refusals include effect_state_incomplete after possible I/O.
                pre_effect = {"root_changed", "path_changed", "snapshot_changed",
                              "changed_since_snapshot"}
                return _result(
                    {"ok": False, "reason": exc.reason, "snapshot_ref": snap.ref},
                    target, op, "refused" if exc.reason in pre_effect else "unknown",
                )
            if not isinstance(exc, OSError):
                logger.warning("file checkpoint capture failed closed: %s", target,
                               exc_info=True)
                return _result(
                    {"ok": False, "reason": "checkpoint_failed", "snapshot_ref": snap.ref},
                    target, op, "unknown",
                )
            self._record(f"file.{op}", f"{target}: io_error", ok=False)
            return _result({
                "ok": False, "reason": "io_error", "detail": exc.__class__.__name__,
                "snapshot_ref": snap.ref,
            }, target, op, "unknown")
        self._record(f"file.{op}", str(target), ok=True, snapshot_ref=snap.ref)
        return _result({
            "ok": True,
            "op": op,
            "path": str(target),
            "bytes": len(data),
            "existed": snap.existed,
            "snapshot_ref": snap.ref,
        }, target, op, "applied", verified=bool(HISTORY_SUPPORTED and verification and verification[0]))

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
        resolved: list[str] = []
        # An unresolvable path is the preflight's refusal to make, not ours — but the
        # spelled name has already been checked, so nothing in the class slips past.
        with contextlib.suppress(FileScopeError, OSError, ValueError):
            target = self.scope.resolve(raw_path)
            names.append(target.name)
            resolved.append(str(target))
        classed = instruction_labels(*names)
        # H507: code-pattern warnings ride on the same card. They never set a class, so
        # the approval stays bound to what H506 classes the write as. The file the write
        # lands on is scanned too, as the write result scans it (review-H507 F4).
        content = (args or {}).get("content")
        if not isinstance(raw_path, str) or not isinstance(content, str):
            return classed
        from .code_guidance import labels as code_labels

        warned = code_labels(raw_path, content, *resolved)
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


def _utf8_page_end(data: bytes, *, allow_empty: bool = False) -> int:
    """How much of *data* to keep so a page never ends inside a UTF-8 character.

    A byte page cut through a multi-byte character decodes as a replacement mark at
    the end of one page and another at the start of the next, so a reader paging a
    perfectly good file reassembles a corrupted one. Dropping the incomplete tail
    moves those bytes to the next page instead. Never returns 0: a page too small for
    one whole character keeps the fragment rather than stall the reader at the same
    offset forever — unless *allow_empty*, for a caller whose next page starts
    elsewhere anyway (a line page moves on to the next line), which then gets 0.
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
        if needed > back and (size - back > 0 or allow_empty):
            return size - back
        return size
    return size


def _line_window_args(args: Mapping[str, Any]) -> tuple[int, int] | str | None:
    """``(first_line, line_count)`` when the read asks for a line window, ``None`` for
    a byte page, or the refusal reason. A window and a byte ``offset`` together are
    refused (``bad_window``): the two count different things, and silently picking
    one would return a page labelled as the other. ``offset: 0`` is the absent offset
    (the start of the file, which every read-back recipe names), not a conflict.
    ``line_numbers: true`` or a ``max_line_chars`` alone is a window too (H303): both
    describe lines, so they start one at line 1 with the default limit."""
    has_start = args.get("line_offset") is not None
    has_limit = args.get("line_limit") is not None
    has_format = args.get("line_numbers") is True or args.get("max_line_chars") is not None
    if not has_start and not has_limit and not has_format:
        return None
    offset = args.get("offset")
    if offset is not None and not (type(offset) is int and offset == 0):
        return "bad_window"
    start = args.get("line_offset", 1) if has_start else 1
    count = args.get("line_limit") if has_limit else DEFAULT_LINE_LIMIT
    if isinstance(start, bool) or not isinstance(start, int) or not 1 <= start <= MAX_OFFSET:
        return "bad_line_offset"
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_LINE_LIMIT:
        return "bad_line_limit"
    return start, count


def _line_format_args(args: Mapping[str, Any]) -> dict[str, Any] | str:
    """How a line window is rendered (H303): ``numbered`` (``line_numbers``) and
    ``line_cap`` (``max_line_chars``, or :data:`DEFAULT_LINE_CHARS` for numbered output,
    or ``None`` for a plain window) — or the refusal reason. The result feeds
    :func:`_line_page` by keyword; for a byte page it is unused."""
    numbered = args.get("line_numbers")
    if numbered is None:
        numbered = False
    elif not isinstance(numbered, bool):
        return "bad_flag"
    cap = args.get("max_line_chars")
    if cap is None:
        cap = DEFAULT_LINE_CHARS if numbered else None
    elif isinstance(cap, bool) or not isinstance(cap, int) or not MIN_LINE_CHARS <= cap <= MAX_LINE_CHARS:
        return "bad_max_line_chars"
    return {"numbered": numbered, "line_cap": cap}


_LINE_CHUNK = 65536


@dataclass(frozen=True)
class _Line:
    """One line as :func:`_read_line` saw it: the first bytes kept, its full length in
    bytes and in characters (the newline included), and the newline it ended with
    (``b""`` at end of input)."""

    kept: bytes
    length: int
    chars: int
    newline: bytes


def _read_line(stream: Any, keep: int) -> _Line | None:
    """One line from *stream* (with its ``\n``): the first *keep* bytes of it and its
    full size, or ``None`` at end of input. A line longer than *keep* is still
    consumed to its end, so the stream always stands at the next line; characters are
    counted on the way (UTF-8 lead bytes), so a cut line can say how much it dropped
    without being held in memory."""
    kept = bytearray()
    length = 0
    chars = 0
    tail = b""
    while True:
        chunk = stream.readline(_LINE_CHUNK)
        if not chunk:
            if not length:
                return None
            break
        length += len(chunk)
        chars += len(chunk.translate(None, _UTF8_CONTINUATION))
        if len(kept) < keep:
            kept += chunk[:keep - len(kept)]
        tail = (tail + chunk[-2:])[-2:]
        if chunk.endswith(b"\n"):
            break
    newline = b"\r\n" if tail.endswith(b"\r\n") else b"\n" if tail.endswith(b"\n") else b""
    return _Line(bytes(kept), length, chars, newline)


def _cap_line(line: _Line, cap: int) -> tuple[bytes, int]:
    """*line* under the per-line cap (H303): its own bytes when it holds at most *cap*
    characters (newline aside), else its first *cap* characters, the
    :data:`LINE_CUT_MARKER` and a newline. The second value is how many characters
    were dropped (0 when none). The caller kept at least ``cap * 4 + 2`` bytes, so a
    line kept only in part is always longer than the cap."""
    text_chars = line.chars - len(line.newline)
    if text_chars <= cap:
        return line.kept, 0
    head = line.kept.decode("utf-8", errors="replace")[:cap]
    dropped = text_chars - cap
    return (head + LINE_CUT_MARKER.format(more=dropped) + "\n").encode("utf-8"), dropped


def _line_page(stream: Any, start: int, count: int, *, budget: int,
               total_lines: int | None = None, numbered: bool = False,
               line_cap: int | None = None) -> dict:
    """A page of up to *count* whole lines starting at line *start* (1-based), never
    more than *budget* bytes (H444).

    A line that would overflow the budget ends the page before it, and
    ``next_line_offset`` names it. A first line bigger than the whole budget comes
    back cut (``line_truncated``) with ``line_byte_offset`` — where that line starts —
    so the rest of it is reachable through the byte ``offset``; the next page then
    starts at the following line. ``total_lines`` is present once the end is known.

    H303 — with *numbered*, every line is prefixed by its number, right-aligned to the
    widest number the window can reach, and a tab (``cat -n``); the prefix counts
    against the budget. With *line_cap*, a line longer than that many characters is
    rendered by :func:`_cap_line` before the budget is applied, so it is one line of
    the page like any other and the paging stays exact (``lines_cut`` counts them).
    """
    line = 1
    while line < start:
        if _read_line(stream, 0) is None:
            break
        line += 1
    width = len(str(start + count - 1)) if numbered else 0
    out = bytearray()
    returned = 0
    lines_cut = 0
    line_truncated = False
    line_byte_offset: int | None = None
    more = True
    while returned < count:
        position = stream.tell()
        prefix = f"{start + returned:>{width}}\t".encode() if numbered else b""
        room = budget - len(out) - len(prefix)
        keep = line_cap * 4 + 2 if line_cap is not None else room + 1
        item = _read_line(stream, max(keep, 1))
        if item is None:
            more = False
            break
        body = item.kept
        length = item.length
        if line_cap is not None:
            body, dropped = _cap_line(item, line_cap)
            length = len(body)
            lines_cut += 1 if dropped else 0
        if length > room:
            if returned == 0:
                # Nothing fits whole: the page holds what it can of this one line (at
                # least one byte after the prefix, so the reader never stalls here).
                cut = body[:max(room, 1)]
                out += prefix
                out += cut[:_utf8_page_end(cut, allow_empty=True)] if len(cut) < length else cut
                returned = 1
                line_truncated = True
                line_byte_offset = position
            else:
                stream.seek(position)
            break
        out += prefix + body
        returned += 1
    if more:
        more = bool(stream.read(1))
    if not more and total_lines is None:
        total_lines = (line - 1) + returned if line == start else line - 1
    data = bytes(out)
    fields: dict[str, Any] = {
        "content": data.decode("utf-8", errors="replace"),
        "bytes": len(data),
        "line_offset": start,
        "lines": returned,
        "truncated": more,
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    if more:
        fields["next_line_offset"] = start + returned
    if total_lines is not None:
        fields["total_lines"] = total_lines
    if line_truncated:
        fields["line_truncated"] = True
        fields["line_byte_offset"] = line_byte_offset
    if numbered:
        fields["line_numbers"] = True
    if line_cap is not None:
        fields["max_line_chars"] = line_cap
        fields["lines_cut"] = lines_cut
    return fields


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


#: H297 — the longest side, in pixels, an image a provider is sent may have: Anthropic
#: rejects the whole request over 8,000 px. A larger image is scaled down to fit.
MAX_IMAGE_SIDE = 8000
#: The most pixels file_read decodes to check an image (about 160 MB as RGBA). A file
#: past it is refused by name; ``raw=true`` still pages its bytes.
MAX_IMAGE_DECODE_PIXELS = 40_000_000
_PIL_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/gif": "GIF", "image/webp": "WEBP"}


def _image_refusal(reason: str, detail: str, **fields: Any) -> dict:
    return {"ok": False, "reason": reason, **fields,
            "detail": f"{detail}; raw=true returns a bounded byte page"}


def _fit_image(data: bytes, media_type: str) -> tuple[bytes, dict] | dict:
    """Decode *data* and bring it within the provider's pixel limit (H297).

    A provider rejects the whole request, not just the image, for an image it
    cannot decode or one over :data:`MAX_IMAGE_SIDE` on a side, so a signature
    check is not enough: the image is decoded here, off the event loop. Returns the
    bytes to send (re-encoded only when scaled down) with their dimensions, or a
    named refusal.
    """
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - pillow is a hard requirement
        return _image_refusal("image_unreadable", "the image decoder is not installed")
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            if image.format != _PIL_FORMATS.get(media_type):
                return _image_refusal("image_unreadable", "the bytes do not decode as " + media_type)
            if width < 1 or height < 1 or width * height > MAX_IMAGE_DECODE_PIXELS:
                return _image_refusal(
                    "image_dimensions_too_large", "the image has too many pixels to send",
                    width=width, height=height, max_pixels=MAX_IMAGE_DECODE_PIXELS)
            image.load()
            if max(width, height) <= MAX_IMAGE_SIDE:
                return data, {"width": width, "height": height}
            if media_type == "image/gif":
                return _image_refusal(
                    "image_dimensions_too_large", "a GIF over the side limit is not rescaled",
                    width=width, height=height, max_side=MAX_IMAGE_SIDE)
            scaled = image.copy()
    except Image.DecompressionBombError:
        return _image_refusal("image_dimensions_too_large", "the image has too many pixels to send",
                              max_pixels=MAX_IMAGE_DECODE_PIXELS)
    except Exception:  # noqa: BLE001 - any decoder failure means the provider would refuse it too
        return _image_refusal("image_unreadable", "the image is corrupt or truncated")
    scaled.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    if media_type == "image/jpeg" and scaled.mode not in ("RGB", "L", "CMYK"):
        scaled = scaled.convert("RGB")
    out = io.BytesIO()
    try:
        scaled.save(out, format=_PIL_FORMATS[media_type])
    except Exception:  # noqa: BLE001 - an encoder failure is a refusal, not a crash
        return _image_refusal("image_unreadable", "the scaled image could not be encoded")
    encoded = out.getvalue()
    if len(encoded) > MAX_IMAGE_BYTES:
        return _image_refusal("image_too_large", "the scaled image is over max_image_bytes",
                              max_image_bytes=MAX_IMAGE_BYTES)
    return encoded, {"width": scaled.width, "height": scaled.height,
                     "original_width": width, "original_height": height}


def _read_image(target: Path, size: int) -> ToolContent | dict | None:
    """An image file as a multimodal result (H297), a bounded refusal, or ``None``.

    ``None`` means the bytes are not the image the suffix names, so the caller pages
    them as an ordinary file. Over :data:`~agents.core.tool_rpc.MAX_IMAGE_BYTES` the
    read is refused by name rather than cut: half an image is a corrupt image. An
    image that does not decode is refused as ``image_unreadable``; one over
    :data:`MAX_IMAGE_SIDE` on a side is scaled down to fit (see :func:`_fit_image`).
    """
    media_type = IMAGE_SUFFIXES[target.suffix.lower()]
    too_large = {
        "ok": False, "reason": "image_too_large", "size": size,
        "max_image_bytes": MAX_IMAGE_BYTES,
        "detail": "images are read whole up to max_image_bytes; raw=true returns a bounded byte page",
    }
    if size > MAX_IMAGE_BYTES:
        return too_large
    with target.open("rb") as handle:
        data = handle.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        return too_large
    if not data or not image_signature_ok(data, media_type):
        return None
    fitted = _fit_image(data, media_type)
    if isinstance(fitted, dict):
        return {**fitted, "path": str(target), "size": size}
    sent, dims = fitted
    digest = hashlib.sha256(data).hexdigest()
    summary = f"{target.name}: {media_type} image, {dims['width']}x{dims['height']} px, {len(sent)} bytes."
    if "original_width" in dims:
        summary += (f" Scaled down from {dims['original_width']}x{dims['original_height']} px"
                    f" to fit the {MAX_IMAGE_SIDE} px provider limit.")
    return ToolContent(
        [ToolContent.text(summary), ToolContent.image(sent, media_type)],
        structured={"ok": True, "path": str(target), "image": True, "media_type": media_type,
                    "bytes": len(data), "size": size, "sha256": digest, **dims},
    )


@dataclass(frozen=True)
class _ParsedDocument:
    """One document's extraction, as every page of it is served (H444)."""

    text: bytes
    total_lines: int
    annotations: dict[str, Any]


class DocumentCache:
    """Parsed documents, keyed by ``(suffix, sha256 of the admitted input bytes)``.

    Content-keyed, so an edited file (same name, same size, same mtime or not) is a
    new key and is parsed again, and an unchanged one is parsed once however many
    pages are read. Least-recently-used entries leave first; the cache holds at most
    :data:`DOCUMENT_CACHE_ENTRIES` documents and :data:`DOCUMENT_CACHE_TEXT_BYTES` of
    extracted text (a larger document is served but not kept). Thread-safe: reads
    run in worker threads.
    """

    def __init__(self, *, max_entries: int = DOCUMENT_CACHE_ENTRIES,
                 max_text_bytes: int = DOCUMENT_CACHE_TEXT_BYTES) -> None:
        self.max_entries = max_entries
        self.max_text_bytes = max_text_bytes
        self._entries: OrderedDict[tuple[str, str], _ParsedDocument] = OrderedDict()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def get(self, key: tuple[str, str]) -> _ParsedDocument | None:
        with self._lock:
            value = self._entries.get(key)
            if value is not None:
                self._entries.move_to_end(key)
            return value

    def put(self, key: tuple[str, str], value: _ParsedDocument) -> None:
        if len(value.text) > self.max_text_bytes:
            return
        with self._lock:
            self._entries[key] = value
            self._entries.move_to_end(key)
            while (len(self._entries) > self.max_entries
                   or sum(len(v.text) for v in self._entries.values()) > self.max_text_bytes):
                self._entries.popitem(last=False)


def _too_large(size: int) -> dict:
    return {
        "ok": False,
        "reason": "document_too_large",
        "size": size,
        "max_document_bytes": MAX_DOCUMENT_BYTES,
        "detail": (
            "document extraction is limited to 50000000 bytes (50 MB); "
            "raw=true returns a bounded byte page"
        ),
    }


def _admitted_bytes(target: Path) -> bytes | int:
    """The document's bytes, read once and bounded: at most one byte past the
    ceiling is read, and a file that grew past it after it was measured comes back
    as its observed size instead, so the parser only ever sees admitted bytes."""
    with target.open("rb") as handle:
        data = handle.read(MAX_DOCUMENT_BYTES + 1)
        if len(data) > MAX_DOCUMENT_BYTES:
            return max(len(data), os.fstat(handle.fileno()).st_size)
    return data


def _count_lines(data: bytes) -> int:
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def _docx_annotations(counts: Mapping[str, int]) -> dict[str, Any]:
    """What a DOCX read says beside its text (H444): the parts it read besides body
    paragraphs (``document_parts``), the visual parts it cannot carry
    (``visual_content``) and the equations it does not extract (``coverage_warning``)."""
    annotations: dict[str, Any] = {}
    parts = {kind: counts[kind] for kind in DOCX_READ_KINDS if counts.get(kind)}
    if parts:
        annotations["document_parts"] = parts
    visual = {kind: int(counts.get(kind, 0)) for kind in DOCX_VISUAL_KINDS}
    if any(visual.values()):
        annotations["visual_content"] = {
            "reason": "docx_images",
            "detail": (
                "This document embeds images, charts, diagrams or objects. file_read "
                "returns only the text and performs no OCR: what they show is not in "
                "the content."
            ),
            **visual,
        }
    if counts.get("equations"):
        annotations["coverage_warning"] = {
            "reason": "docx_content_not_extracted",
            "detail": (
                "This document holds equations, which are not extracted: the text "
                "around them is complete, the equations themselves are missing."
            ),
            "equations": int(counts["equations"]),
        }
    return annotations


def _parse_document(suffix: str, data: bytes, target: Path) -> _ParsedDocument | None:
    stream = io.BytesIO(data)
    stream.name = str(target)  # type: ignore[attr-defined]  # what a parser error names
    extract = extract_pdf_document if suffix == ".pdf" else extract_docx_document
    result = extract(stream)
    if not isinstance(result, DocumentExtraction):
        return None
    annotations: dict[str, Any] = {}
    if suffix == ".pdf":
        coverage = pdf_coverage_warning(result.pages)
        if coverage is not None:
            annotations["coverage_warning"] = coverage
        if result.image_pages:
            ranges = page_ranges(result.image_pages)
            annotations["visual_content"] = {
                "reason": "pdf_pages_with_images",
                "detail": (
                    "These pages hold embedded images. file_read returns only the text "
                    "layer and performs no OCR: charts, scans and pictures on them are "
                    "not in the content."
                ),
                "pages_with_images": len(result.image_pages),
                "ranges": ranges["ranges"],
                "omitted_range_count": ranges["omitted_range_count"],
            }
    else:
        annotations.update(_docx_annotations(result.content_counts))
    if result.stopped is not None:
        limit = ("the extracted-text ceiling" if result.stopped == "text_limit"
                 else "the extraction time budget")
        retry = ("" if result.stopped == "text_limit" else
                 " The time budget depends on load, so this result is not cached: "
                 "reading the file again parses the document again.")
        annotations["extraction_incomplete"] = {
            "reason": result.stopped,
            "unit": result.unit,
            "units_read": result.units_read,
            "units_total": result.units_total,
            "detail": (
                f"Extraction stopped at {limit} after {result.units_read} of "
                f"{result.units_total} {result.unit}s; the text ends there and is not "
                f"the whole document.{retry}"
            ),
        }
    text = result.text.encode("utf-8")
    return _ParsedDocument(text=text, total_lines=_count_lines(text), annotations=annotations)


def _read_document(target: Path, size: int, limit: int, offset: int = 0, *,
                   cache: DocumentCache | None = None,
                   window: tuple[int, int] | None = None,
                   line_format: Mapping[str, Any] | None = None) -> dict:
    """Extract a bounded text page from an admitted .pdf / .docx input.

    ``offset`` counts bytes of the *extracted text* (UTF-8), not of the file: that is
    the text the reader was shown, so it is the only thing a page number can mean.
    ``window`` (``line_offset``, ``line_limit``) pages the same text by lines instead,
    rendered as ``line_format`` says (:func:`_line_format_args`, H303).
    ``size`` is the observed on-disk input size; refuse above 50,000,000 bytes
    before probing a parser. ``text_size`` names the extracted text's byte size.

    H444 — the parser reads the bytes admitted here (bounded, read once), never the
    path, and its result is kept in *cache* under the SHA-256 of those bytes, so the
    next page of an unchanged document is served without parsing it again
    (``cached``). Extraction runs within a text-size and time budget
    (``extraction_incomplete`` when one ran out).
    """
    if size > MAX_DOCUMENT_BYTES:
        return _too_large(size)
    suffix = target.suffix.lower()
    if not _parser_available(suffix):
        return {
            "ok": False,
            "reason": "parser_missing",
            "detail": f"reading {suffix} needs the {_DOCUMENT_PARSERS[suffix]} package; raw=true returns the bytes",
        }
    data = _admitted_bytes(target)
    if isinstance(data, int):
        return _too_large(data)
    key = (suffix, hashlib.sha256(data).hexdigest())
    parsed = cache.get(key) if cache is not None else None
    cached = parsed is not None
    if parsed is None:
        parsed = _parse_document(suffix, data, target)
        if parsed is None:
            return {"ok": False, "reason": "extraction_failed", "detail": "the file could not be parsed"}
        stop = parsed.annotations.get("extraction_incomplete", {}).get("reason")
        if cache is not None and stop != "time_limit":
            # A time-budget stop depends on machine load: caching it would serve the
            # truncated prefix to every later read. A text-budget stop is
            # deterministic and stays cached.
            cache.put(key, parsed)
    text = parsed.text
    if window is not None:
        page = _line_page(io.BytesIO(text), *window, budget=limit, total_lines=parsed.total_lines,
                          **(line_format or {}))
    else:
        page = _page(text[offset:offset + limit], offset=offset, total=len(text))
    return {
        "ok": True,
        "path": str(target),
        **parsed.annotations,
        **page,
        "size": size,
        "text_size": len(text),
        "extracted": True,
        "format": suffix.lstrip("."),
        "cached": cached,
    }


def _gitignore_dirs(root: Path) -> tuple[frozenset[str], frozenset[str]]:
    """Directories *root*'s ``.gitignore`` names plainly (H303): ``(anywhere, rooted)``.

    Only the cheap, safe subset is honoured — a line that is a directory name or path
    with no wildcard (``node_modules``, ``build/``, ``/out``, ``docs/_build``). A name
    without a ``/`` applies at any depth, one with a ``/`` only at that path below
    *root*. Patterns with wildcards are not read, and a ``.gitignore`` with a ``!``
    re-include line is not read at all (it could re-include what a plain line hides).
    Pruning is all this feeds, so a pattern it does not understand costs nothing but
    a directory being searched."""
    path = root / ".gitignore"
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_GITIGNORE_BYTES:
            return frozenset(), frozenset()
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return frozenset(), frozenset()
    anywhere: set[str] = set()
    rooted: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("!"):
            return frozenset(), frozenset()
        if not line or line.startswith("#") or any(ch in line for ch in "*?[\\"):
            continue
        anchored = line.startswith("/") or "/" in line.rstrip("/")
        name = line.strip("/")
        if not name or name in (".", ".."):
            continue
        (rooted if anchored else anywhere).add(name)
    return frozenset(anywhere), frozenset(rooted)


def _walk_files(target: Path, root: Path, counts: dict[str, Any], *,
                skip_dirs: frozenset[str] = frozenset(),
                skip_rooted: frozenset[str] = frozenset(),
                deadline: float | None = None, max_entries: int | None = None):
    """Yield ``(path, size)`` for every regular file under *target* the read tools
    would show: symlinks are never followed (counted), secret-looking names and
    directories are pruned (counted as hidden), everything else is visited in
    sorted order so a search is deterministic.

    H303 — a directory below *target* whose name is in *skip_dirs*, or whose path below
    *root* is in *skip_rooted*, is not entered (counted as ``ignored``): the search
    tools prune dependency and build trees this way (:data:`NOISE_DIRS`, a plain
    ``.gitignore``). *target* itself is never pruned.

    Every entry the walk meets — yielded or not (a secret name, a symlink, a pruned
    directory) — counts in ``counts["entries"]``. Past *max_entries* entries, or past
    *deadline* (checked every 64 entries), the walk ends and ``counts["walk_stopped"]``
    names why (``max_files`` / ``deadline``), so a tree made only of names the read tools
    never show cannot outrun the caps the consumer applies to what is yielded."""
    if target.is_file():
        yield target, target.stat().st_size
        return

    def exhausted() -> bool:
        counts["entries"] = counts.get("entries", 0) + 1
        if max_entries is not None and counts["entries"] > max_entries:
            counts["walk_stopped"] = "max_files"
            return True
        if deadline is not None and counts["entries"] % 64 == 0 and time.monotonic() > deadline:
            counts["walk_stopped"] = "deadline"
            return True
        return False

    for dirpath, dirnames, filenames in os.walk(target, topdown=True, followlinks=False):
        here = Path(dirpath)
        try:
            relative = here.relative_to(root).parts
        except ValueError:
            relative = ()
        kept: list[str] = []
        for name in sorted(dirnames):
            if exhausted():
                return
            if os.path.islink(here / name):
                counts["symlink"] += 1
            elif _has_secret_part((*relative, name)):
                counts["hidden"] += 1
            elif name in skip_dirs or "/".join((*relative, name)) in skip_rooted:
                counts["ignored"] = counts.get("ignored", 0) + 1
            else:
                kept.append(name)
        dirnames[:] = kept
        for name in sorted(filenames):
            if exhausted():
                return
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


def _text_lines(text: str) -> list[str]:
    """*text* as the lines a search numbers: split on ``\\n`` only (``\\r`` stripped),
    the way editors and ``file_read``'s line windows count them — not
    ``str.splitlines``, which also breaks on form feeds and Unicode separators and would
    number lines differently from both (H303)."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [line[:-1] if line.endswith("\r") else line for line in lines]


def _expand_braces(glob: str, budget: int = MAX_GLOB_ALTERNATIVES) -> list[str] | None:
    """*glob* with every ``{a,b}`` alternation expanded (nesting allowed), or ``None``
    when that would give more than *budget* globs. A ``{`` with no matching ``}`` or no
    top-level comma is an ordinary character."""
    start = glob.find("{")
    while start != -1:
        depth = 0
        commas: list[int] = []
        end = start
        while end < len(glob):
            char = glob[end]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    break
            elif char == "," and depth == 1:
                commas.append(end)
            end += 1
        if end < len(glob) and commas:
            head, tail = glob[:start], glob[end + 1:]
            bounds = [start, *commas, end]
            out: list[str] = []
            for left, right in zip(bounds, bounds[1:], strict=False):
                sub = _expand_braces(head + glob[left + 1:right] + tail, budget)
                if sub is None:
                    return None
                out.extend(sub)
                if len(out) > budget:
                    return None
            return out
        start = glob.find("{", start + 1)
    return [glob]


def _compile_glob(glob: str) -> tuple[bool, tuple[str, ...]] | None:
    """``(negated, alternatives)`` for a search glob, or ``None`` when it is not one
    (H303). A leading ``!`` negates the whole glob (files that do NOT match), braces
    expand to at most :data:`MAX_GLOB_ALTERNATIVES` globs, and no alternative may be an
    absolute path or empty."""
    negated = glob.startswith("!")
    body = glob[1:] if negated else glob
    alternatives = _expand_braces(body) if body else None
    if not alternatives or any(not alt or alt.startswith("/") for alt in alternatives):
        return None
    return negated, tuple(alternatives)


def _glob_one(file: Path, target: Path, glob: str) -> bool:
    """One plain glob (``* ? [seq]``, no braces or negation) against *file*: a glob
    without ``/`` is matched against the file name, one with ``/`` against the POSIX
    path relative to *target* (``*`` crosses directories, so ``**/*.py`` and
    ``src/*.py`` both work, and a ``**/`` segment, leading or embedded, also matches at
    depth zero, as in gitignore / ripgrep globs). Case matters, as on the disk the roots name."""
    if "/" not in glob:
        return fnmatch.fnmatchcase(file.name, glob)
    try:
        relative = file.relative_to(target).as_posix()
    except ValueError:
        relative = file.name
    if relative == ".":
        relative = file.name
    return any(fnmatch.fnmatchcase(relative, variant) for variant in _zero_depth_variants(glob))


_GLOBSTAR_SEGMENT = re.compile(r"(?:(?<=/)|^)\*\*/")
_MAX_GLOBSTAR_SEGMENTS = 4


def _zero_depth_variants(glob: str) -> list[str]:
    """*glob* itself plus every spelling with some of its ``**/`` segments dropped, so
    ``src/**/*.ts`` also matches ``src/a.ts`` (a ``**/`` may span zero directories, as in
    gitignore / ripgrep globs). More than :data:`_MAX_GLOBSTAR_SEGMENTS` of them: only the
    original and the fully collapsed spelling."""
    spans = [m.span() for m in _GLOBSTAR_SEGMENT.finditer(glob)]
    if not spans:
        return [glob]
    if len(spans) > _MAX_GLOBSTAR_SEGMENTS:
        return [glob, _GLOBSTAR_SEGMENT.sub("", glob)]
    variants = []
    for mask in range(1 << len(spans)):
        out, last = [], 0
        for i, (a, b) in enumerate(spans):
            out.append(glob[last:a])
            out.append("" if mask & (1 << i) else glob[a:b])
            last = b
        out.append(glob[last:])
        variants.append("".join(out))
    return variants


def _glob_matches(file: Path, target: Path, glob: tuple[bool, tuple[str, ...]]) -> bool:
    """Whether *file* (under *target*) matches a glob compiled by :func:`_compile_glob`
    (H303): any alternative matches, inverted for a negated glob."""
    negated, alternatives = glob
    return any(_glob_one(file, target, alt) for alt in alternatives) != negated


def _regex_too_complex(pattern: str) -> bool:
    """True when *pattern* nests one unbounded repeat inside another (``(a+)+``,
    ``(\\w*)*``, ``((ab)*)+``): star height above one, the shape Python's backtracking
    ``re`` cannot bound. It is refused up front (``regex_too_complex``) as a cheap
    first line of defence; the guarantee is the killable child (:func:`_py_regex_scan`),
    because patterns such as ``(a|aa)+$`` have star height one and still backtrack
    without bound. A pattern the parser rejects is left for ``re.compile`` to name
    (``bad_regex``)."""
    try:
        from re import _parser as parser  # CPython 3.11+ (the former sre_parse)

        tree = parser.parse(pattern)
    except Exception:
        return False
    repeats = {parser.MAX_REPEAT, parser.MIN_REPEAT}
    possessive = getattr(parser, "POSSESSIVE_REPEAT", None)
    if possessive is not None:
        repeats.add(possessive)

    def subpatterns(value: Any):
        if isinstance(value, parser.SubPattern):
            yield value
        elif isinstance(value, (tuple, list)):
            for item in value:
                yield from subpatterns(item)

    def nested(items: Any, inside_unbounded: bool) -> bool:
        for op, av in items:
            if op in repeats:
                _lo, hi, sub = av
                unbounded = hi == parser.MAXREPEAT
                if unbounded and inside_unbounded:
                    return True
                if nested(sub, inside_unbounded or unbounded):
                    return True
            else:
                for sub in subpatterns(av):
                    if nested(sub, inside_unbounded):
                        return True
        return False

    return nested(tree, False)


def _portability_error(pattern: str) -> str | None:
    """Why *pattern* would silently mean something other than what a model that knows
    ripgrep, PCRE or POSIX regexes wrote, or ``None`` (H303). The engine is Python's
    ``re``, which reads these differently, so they are refused (``bad_regex``) with a
    message that says how to write what was probably meant, instead of matching
    something else:

    * a ``[`` inside a character class — a POSIX class (``[[:alpha:]]``) or a nested
      set. ``re`` silently reads a different set (and warns);
    * ``--``, ``&&``, ``~~`` or ``||`` inside a class — set operators elsewhere,
      literal characters in ``re``;
    * ``\\<`` and ``\\>`` — word boundaries elsewhere, literal characters in ``re``.
    """
    in_class = False
    i = 0
    size = len(pattern)
    while i < size:
        char = pattern[i]
        if char == "\\":
            follower = pattern[i + 1:i + 2]
            if follower in ("<", ">"):
                return (f"\\{follower} is a word boundary in other regex flavours but a literal in Python; "
                        f"write {follower} or \\b")
            i += 2
            continue
        if in_class:
            if char == "[":
                return ("a [ inside a character class (POSIX [[:alpha:]] or a nested set) is "
                        "read differently by Python than by POSIX/ripgrep; escape it as \\[ or use "
                        "\\w, \\d or a range such as a-z")
            if char in "-&~|" and pattern[i + 1:i + 2] == char:
                return (f"'{char}{char}' inside a character class is a set operator in "
                        "other regex flavours but literal in Python; escape it")
            if char == "]":
                in_class = False
            i += 1
            continue
        i += 1
        if char == "[":
            in_class = True
            if pattern[i:i + 1] == "^":
                i += 1
            if pattern[i:i + 1] == "]":
                i += 1
    return None


def _regex_source(pattern: str, whole_word: bool) -> str:
    """The regex both engines run: *pattern*, wrapped so the match has no word
    character on either side when *whole_word* (what ``grep -w`` means)."""
    return f"(?<!\\w)(?:{pattern})(?!\\w)" if whole_word else pattern


def _compile_regex(pattern: str, *, case_sensitive: bool, whole_word: bool) -> re.Pattern[str]:
    """Validate *pattern* for a regex search (H303), the check both engines share:
    ``re.error`` for a bad or non-portable regex (:func:`_portability_error`),
    ``regex_too_complex`` for star height above one, else the compiled pattern.
    ``whole_word`` requires a non-word character (or an edge) on both sides of the
    match, which is what ``grep -w`` and the literal mode mean by it."""
    problem = _portability_error(pattern)
    if problem is not None:
        raise re.error(problem)
    if _regex_too_complex(pattern):
        raise ToolRPCValidationError("regex_too_complex")
    return re.compile(_regex_source(pattern, whole_word), 0 if case_sensitive else re.IGNORECASE)


def _regex_error(pattern: object) -> str:
    """What is wrong with *pattern*, for a ``bad_regex`` refusal (``re``'s own words,
    bounded)."""
    try:
        _compile_regex(pattern if isinstance(pattern, str) else "", case_sensitive=True,
                       whole_word=False)
    except re.error as exc:
        return str(exc)[:200]
    except ToolRPCValidationError:
        pass
    return "invalid regular expression"


#: H303 — the Python regex engine's child process. It is a plain script run by the
#: backend's own interpreter (``-I -S``: no site, no user environment) so that a pattern
#: Python's backtracking ``re`` cannot finish — ``(a|aa)+$`` on a long line — is a
#: process the parent kills at the search deadline, never a thread it cannot stop. It
#: reads one JSON request on stdin (the pattern source, the files, the caps), decodes
#: each file as UTF-8 with replacement characters (so a latin-1 file is searched, as the
#: literal mode does), splits it on ``\n`` only (``\r`` stripped, the way editors count
#: lines), matches the WHOLE line (no window) and writes one JSON record per file,
#: flushed, so the rows of the files finished before a kill are kept. Its ``_snip`` is
#: :func:`_snippet`; tests pin that the two agree.
_PY_SCAN_WORKER = r'''
import json, os, re, sys
req = json.loads(sys.stdin.buffer.read())
rx = re.compile(req["source"], re.IGNORECASE if req["ignore_case"] else 0)
SNIP = req["snippet_chars"]
def _snip(line, index, width):
    if len(line) <= SNIP:
        return line
    index = max(0, min(index, len(line)))
    half = max(0, (SNIP - min(width, SNIP)) // 2)
    start = max(0, index - half)
    end = min(len(line), start + SNIP)
    start = max(0, end - SNIP)
    out = line[start:end]
    if start > 0:
        out = "…" + out
    if end < len(line):
        out = out + "…"
    return out
flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
for number, path in enumerate(req["files"]):
    rows, capped = [], False
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as handle:
            data = handle.read(req["max_bytes"])
    except OSError:
        data = b""
    lines = data.decode("utf-8", errors="replace").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    for lineno, line in enumerate(lines, 1):
        if line.endswith("\r"):
            line = line[:-1]
        found = rx.search(line)
        if found is None:
            continue
        if len(rows) >= req["per_file"]:
            capped = True
            break
        rows.append([lineno, _snip(line, found.start(), max(1, found.end() - found.start()))])
    sys.stdout.write(json.dumps({"f": number, "rows": rows, "capped": capped}) + "\n")
    sys.stdout.flush()
'''


def _py_regex_scan(files: Sequence[Path], source: str, *, ignore_case: bool, deadline: float,
                   max_bytes: int,
                   ) -> tuple[dict[Path, tuple[list[dict], bool]], bool] | None:
    """The Python regex engine over *files* (H303): ``({file: (rows, capped)}, timed_out)``
    for the files whose scan finished, or ``None`` when it cannot run (a frozen
    build has no Python to start; the caller then says ``regex_unavailable``).

    The scan runs in a child interpreter (:data:`_PY_SCAN_WORKER`) that is killed at
    *deadline*; ``timed_out`` is true then, and the dict holds only the files finished
    before the kill. No shell, stdin carries the request, and the child gets a scrubbed
    environment. The files are the walk's, opened without following a symlink."""
    if getattr(sys, "frozen", False) or not sys.executable:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return {}, True
    request = json.dumps({
        "source": source, "ignore_case": ignore_case, "files": [str(file) for file in files],
        "max_bytes": max_bytes, "per_file": MAX_MATCHES_PER_FILE, "snippet_chars": SNIPPET_CHARS,
    }).encode("utf-8")
    env = {key: value for key, value in os.environ.items()
           if key in ("PATH", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL")}
    timed_out = False
    try:
        proc = subprocess.run(  # nosec B603 - fixed argv, no shell, scrubbed env
            [sys.executable, "-I", "-S", "-c", _PY_SCAN_WORKER], input=request,
            capture_output=True, timeout=max(0.05, remaining), env=env, check=False,
        )
        stdout, code = proc.stdout or b"", proc.returncode
    except subprocess.TimeoutExpired as exc:
        stdout, code, timed_out = exc.stdout or b"", 0, True
    except (OSError, ValueError):
        return None
    result: dict[Path, tuple[list[dict], bool]] = {}
    for raw in stdout.splitlines():
        try:
            record = json.loads(raw)
            file = files[record["f"]]
            rows = [{"path": str(file), "line": int(n), "text": str(text)}
                    for n, text in record["rows"]]
        except (ValueError, KeyError, IndexError, TypeError):
            continue  # a record cut by the kill
        result[file] = (rows, bool(record.get("capped")))
    if code != 0 and not timed_out:
        return None
    return result, timed_out


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
    for name in ("line_offset", "line_limit", "line_numbers", "max_line_chars"):
        if name in args:
            clean[name] = args[name]
    if "line_numbers" in clean or "max_line_chars" in clean:
        line_format = _line_format_args(clean)
        if isinstance(line_format, str):
            raise ToolRPCValidationError(line_format)
    if any(name in clean for name in ("line_offset", "line_limit", "line_numbers", "max_line_chars")):
        window = _line_window_args(clean)
        if isinstance(window, str):
            raise ToolRPCValidationError(window)
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
    """The search arguments, checked: a ``pattern`` (content search) or a ``glob``
    alone (file finding, H303) — neither is ``bad_pattern``; ``regex`` needs a
    pattern that compiles (``bad_regex``) and keeps star height one
    (``regex_too_complex``); a glob may hold ``/``, ``{a,b}`` alternation (at most
    :data:`MAX_GLOB_ALTERNATIVES` expansions) and a leading ``!`` negation, but no
    alternative may start with ``/`` (``bad_glob``)."""
    clean: dict[str, Any] = {}
    pattern = args.get("pattern")
    if pattern is not None:
        if (
            not isinstance(pattern, str) or not pattern or len(pattern) > MAX_PATTERN_CHARS
            or "\x00" in pattern
        ):
            raise ToolRPCValidationError("bad_pattern")
        clean["pattern"] = pattern
    path = _path_arg(args, required=False)
    if path is not None:
        clean["path"] = path
    for flag in ("case_sensitive", "whole_word", "regex", "include_ignored"):
        if flag in args:
            if not isinstance(args[flag], bool):
                raise ToolRPCValidationError("bad_flag")
            clean[flag] = args[flag]
    if "glob" in args:
        glob = args["glob"]
        if (
            not isinstance(glob, str) or not glob or len(glob) > MAX_GLOB_CHARS
            or "\x00" in glob or "\\" in glob or _compile_glob(glob) is None
        ):
            raise ToolRPCValidationError("bad_glob")
        clean["glob"] = glob
    if pattern is None and (clean.get("glob") is None or clean.get("regex")):
        raise ToolRPCValidationError("bad_pattern")
    if clean.get("regex"):
        try:
            _compile_regex(pattern, case_sensitive=bool(clean.get("case_sensitive")),
                           whole_word=bool(clean.get("whole_word")))
        except re.error:
            raise ToolRPCValidationError("bad_regex") from None
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
            "pass it back as offset to page through a large file or a spilled tool result. "
            "Or read by lines: line_offset (1-based first line) and line_limit (default "
            "500, at most 2000) return whole lines, and next_line_offset names the next "
            "page; a byte offset other than 0 and a line window cannot be combined. "
            "line_numbers=true prefixes each line with its number (cat -n style) — the mode "
            "for reading code — and max_line_chars (8..100000; default 2000 when numbered, "
            "no cap otherwise) cuts a longer line with a ' …[+N chars]' marker while it "
            "still counts as one line, so a minified line cannot fill a page by itself. "
            "PDF/DOCX extraction accepts at most 50 MB (50,000,000 bytes); raw=true pages bytes. "
            "A .docx is read in document order: tables as | rows, text boxes, "
            "headers/footers and notes included; its images, charts and objects (no OCR) "
            "and equations are reported beside the content. "
            "PDF page gaps without extracted text, pages of garbled text and pages "
            "holding images (no OCR is done) are reported separately from content; an "
            "unchanged document is parsed once and later pages come from cache. "
            "A .png/.jpg/.gif/.webp image (up to 3,750,000 bytes) is returned as the image "
            "itself; raw=true returns its bytes."
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
                "line_offset": {"type": "integer", "minimum": 1, "maximum": MAX_OFFSET},
                "line_limit": {"type": "integer", "minimum": 1, "maximum": MAX_LINE_LIMIT},
                "line_numbers": {"type": "boolean"},
                "max_line_chars": {"type": "integer", "minimum": MIN_LINE_CHARS,
                                   "maximum": MAX_LINE_CHARS},
                "raw": {"type": "boolean"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "preflight": _preflight_read,
    },
    "file_list": {
        "description": (
            "List one directory inside the owner's file roots (bounded entries, not "
            "recursive). To find files by name across subdirectories use file_search "
            "with glob and no pattern."
        ),
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
            "Search file contents inside the owner's file roots — the replacement for "
            "grep/rg/find in a terminal. pattern is a literal phrase (case-insensitive "
            "unless case_sensitive; whole_word available) or, with regex=true, a regular "
            "expression in PYTHON re syntax (\\\\w \\\\d \\\\s \\\\b are Unicode; no POSIX classes), "
            "matched against whole lines in a child process that is killed at the "
            "deadline: an invalid regex or one meaning something else elsewhere — a POSIX "
            "class like [[:alpha:]], \\\\< or \\\\>, a nested set — is refused as bad_regex, a "
            "nested unbounded repeat like (a+)+ as regex_too_complex, and a pattern that "
            "cannot finish in time stops with stopped_by 'deadline' and the rows found so "
            "far. Returns bounded snippets with path and line; "
            "says when a cap stopped the search. glob narrows the files; glob WITHOUT "
            "pattern finds files recursively (mode 'glob': files with their size, bounded "
            "by max_matches) — use it instead of walking directories with file_list. "
            "Glob syntax: * ? [abc] [!abc]; {py,md} alternation ('*.{py,md}', at most 32 "
            "expansions); a leading ! negates ('!*.min.js' = files that do not match); a "
            "glob without / matches the file name ('*.py'), one with / matches the path "
            "relative to path ('src/**/*.ts', '**/' also matches depth zero); case "
            "matters; no absolute paths. node_modules, venv/.venv, __pycache__, dist, "
            "build, target, .tox, caches and plain directory names in the root's "
            ".gitignore are not entered (reported as ignored) unless include_ignored=true; "
            "a path inside one is searched. Secret-looking files are never searched."
        ),
        "gated": False,
        "trusted_execution": False,
        "capability_id": "tool:file_search",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "minLength": 1, "maxLength": MAX_PATTERN_CHARS},
                "regex": {"type": "boolean"},
                "include_ignored": {"type": "boolean"},
                "path": _PATH_SCHEMA,
                "glob": {"type": "string", "minLength": 1, "maxLength": MAX_GLOB_CHARS},
                "case_sensitive": {"type": "boolean"},
                "whole_word": {"type": "boolean"},
                "max_matches": {"type": "integer", "minimum": 1, "maximum": MAX_SEARCH_MATCHES},
            },
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
    mutation_intake: Callable[[str, str, dict, Mapping[str, Any] | None], int] | None = None,
) -> list[str]:
    """Register the five file tools on a ToolRPC server. Default-off: returns
    ``[]`` without touching the server unless ``JARVIS_FILE_TOOLS`` is on (or
    ``enabled=True`` is passed explicitly)."""
    on = file_tools_enabled() if enabled is None else bool(enabled)
    if not on:
        return []
    if mutation_intake is not None and not callable(mutation_intake):
        raise ValueError("mutation_intake must be callable")
    instance = tools if tools is not None else FileTools.from_env()

    def _current_instance():
        from .kanban.workspace_context import file_tools_for_workspace

        return file_tools_for_workspace(instance)

    def _preflight(name):
        def validate(args):
            try:
                current = _current_instance()
            except FileScopeError as exc:
                raise ToolRPCValidationError(exc.reason) from None
            return current.preflight(name)(args)
        return validate

    async def _read(args: dict) -> dict:
        return await _current_instance().read_file(args)

    async def _list(args: dict) -> dict:
        return await _current_instance().list_dir(args)

    async def _search(args: dict) -> dict:
        return await _current_instance().search_files(args)

    async def _write(args: dict) -> dict:
        # Reached only through ToolRPCServer.execute after durable approval
        # (gated tools never run inline from handle()), and only after that
        # execute matched the call's H506 class against the approved card.
        return await _current_instance().write_file(args, approved=True)

    async def _delete(args: dict) -> dict:
        return await _current_instance().delete_file(args, approved=True)

    def _classify(args: dict) -> Mapping[str, Any] | None:
        # H506 — server-owned, registered here, never selectable by call data: a
        # sandboxed script cannot label its own write, nor strip the label off one.
        return _current_instance().classify_mutation(args)

    def _gated_intake(name: str):
        def intake(actor: str, args: dict) -> int:
            # The registrar owns this callback. Recheck the worker binding at the
            # last synchronous boundary before the coordinator queues its action.
            try:
                current = _current_instance()
                labels = current.classify_mutation(args)
                latest = _current_instance()
                if getattr(current, "binding", None) is not getattr(latest, "binding", None):
                    raise FileScopeError("outside_scope")
            except FileScopeError as exc:
                raise ToolRPCValidationError(exc.reason) from None
            return mutation_intake(actor, name, args, labels)

        return intake

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
            preflight=_preflight(name),
            trusted_execution=spec["trusted_execution"],
            classifier=classifiers.get(name),
            gated_intake=_gated_intake(name) if mutation_intake is not None and spec["gated"] else None,
            # H399 — a mutation runs alone: a read of the same path in the same step
            # must see it either wholly before or wholly after, never mid-write.
            parallel_safe=False if spec["gated"] else None,
        )
        registered.append(name)
    return registered


__all__ = [
    "KIND", "FLAG", "ROOTS_ENV", "MAX_BYTES_ENV", "DEFAULT_MAX_BYTES", "MAX_OFFSET", "IMAGE_SUFFIXES",
    "FILE_WRITE_CONTRACT", "FILE_TOOL_SPECS", "GATED_TOOL_KINDS",
    "FileScope", "FileScopeError", "FileTools", "Snapshot", "SnapshotStore",
    "SECRET_NAME_TOKENS", "looks_secret_name", "restore_snapshot", "register_file_tools",
    "INSTRUCTION_BASE_NAMES", "INSTRUCTION_FILE_NAMES", "INSTRUCTION_FILE_SUFFIXES",
    "INSTRUCTION_CLASS", "INSTRUCTION_NOTICE",
    "looks_instruction_name", "instruction_labels",
    "file_tools_enabled",
]
