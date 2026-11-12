"""H025 — ``nerva skills tap | snapshot | diff``: extra skill sources, a portable skill set,
and what the owner changed in a stock skill.

* ``nerva skills tap list|add|remove|refresh`` drive the hub's taps routes (G20,
  ``agents/core/routers/skill_taps.py``). ``add`` only queues the owner's irreversible-tier
  approval card (``skills.tap_add``) with the source URL on it; ``remove`` narrows trust and
  is immediate; ``refresh`` reads an approved tap's index at its pinned commit through the
  hub's governed egress.
* ``nerva skills snapshot export FILE|-`` writes the installed catalog and tap skills (with
  the exact commit, path and SKILL.md sha256 of each), the Nerva optional skills installed
  and the owner's taps to a JSON file.
  ``nerva skills snapshot import FILE`` replays it on another hub through the same owner
  routes one install at a time — a missing tap is *requested* (a card, never trusted by the
  file), each skill crosses its own install path (``skill.install``, quarantine) — and is
  resumable: what is installed already is skipped, what waits for a card is named.
* ``nerva skills diff NAME`` (offline, same data root) prints a unified diff of a stock skill
  the owner installed — from the vendored Hermes catalog (against its byte-verified copy) or
  one of Nerva's shipped optional skills (against ``optional-skills/<slug>``).

Everything the hub or a file says is validated before use and passes through ``_plain``
before it reaches the terminal; local files are opened without following links and only
when they are regular files, with a size cap.
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import hashlib
import hmac
import itertools
import json
import os
import re
import stat
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urlencode

TAPS = "/api/skills/taps"
TAP_SEARCH = "/api/skills/taps/search"
SEARCH_MAX = 100
#: ``list-modified`` looks at most at this many installed skill folders.
MAX_INSTALLED_FOLDERS = 1000
TAP_INSTALL = "/api/skills/taps/install"
IMPORTED = "/skills/imported"
CATALOG_INSTALL = "/api/skills/catalog/install"
OPTIONAL_INSTALL = "/api/skills/optional/install"
OPTIONAL_CATALOG = "/api/skills/optional/catalog"
OPTIONAL_SOURCE = "nerva-optional"

SNAPSHOT_FORMAT = "nerva-skills-snapshot"
SNAPSHOT_VERSION = 1
#: A snapshot file larger than this is refused unread.
MAX_SNAPSHOT_BYTES = 1 << 20
MAX_SNAPSHOT_SKILLS = 500
MAX_SNAPSHOT_TAPS = 32
#: ``diff`` reads at most this many bytes of one local file, this many files, this deep.
MAX_DIFF_FILE_BYTES = 256 * 1024
MAX_DIFF_FILES = 200
MAX_DIFF_DEPTH = 6
#: ``diff`` looks at most at this many directory entries in all (files and folders).
MAX_DIFF_ENTRIES = 2000
#: ``diff`` prints at most this many diff lines in all.
MAX_DIFF_LINES = 4000

_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA64 = re.compile(r"[0-9a-f]{64}\Z")
_SLUG = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
#: Nerva's shipped optional skills are folder names like ``email_triage``.
_OPTIONAL_SLUG = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_TAP_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,99}--[a-z0-9][a-z0-9._-]{0,99}\Z")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,127}\Z")


def _plain(text: Any, width: int = 200) -> str:
    """One terminal-safe line: C0/C1 controls, bidi and invisible format characters removed
    (the CLI's own sanitiser, ``agents.cli.nerva._plain``)."""
    from .nerva import _plain as plain

    return plain(text, width)


def _dump(ctx, payload: Any) -> None:
    """JSON with every non-ASCII character escaped, so nothing invisible reaches the terminal."""
    ctx.out.write(json.dumps(payload, indent=2, ensure_ascii=True, default=str) + "\n")


def register(skills_verbs) -> None:
    tap = skills_verbs.add_parser(
        "tap", help="extra skill sources (GitHub repositories pinned to one commit); adding one waits "
                    "for your approval card (admin)")
    tap_verbs = tap.add_subparsers(dest="tap_action", required=True, metavar="action")
    tap_verbs.add_parser("list", help="the built-in sources and your taps, with trust and status").add_argument(
        "--json", action="store_true")
    add = tap_verbs.add_parser("add", help="ask to trust a repository at one exact commit (an approval card)")
    add.add_argument("repo", help="owner/repo on GitHub")
    add.add_argument("--commit", required=True, metavar="SHA", help="the exact 40-hex commit; branches move")
    add.add_argument("--path", default="skills", help="the folder holding one folder per skill (default skills)")
    add.add_argument("--trust", choices=("community", "trusted"), default="community")
    add.add_argument("--json", action="store_true")
    remove = tap_verbs.add_parser("remove", help="stop trusting a tap (immediate; installed skills stay)")
    remove.add_argument("tap", help="the tap id (owner--repo) or owner/repo")
    remove.add_argument("--json", action="store_true")
    refresh = tap_verbs.add_parser("refresh", help="read an approved tap's skill index at its pinned commit")
    refresh.add_argument("tap", help="the tap id (owner--repo) or owner/repo")
    refresh.add_argument("--json", action="store_true")

    snapshot = skills_verbs.add_parser(
        "snapshot", help="write the installed skill set to a file, or replay one on this hub")
    snap_verbs = snapshot.add_subparsers(dest="snapshot_action", required=True, metavar="action")
    export = snap_verbs.add_parser("export", help="write catalog and tap skills plus your taps to a JSON file")
    export.add_argument("output", help="the file to write, or - for standard output")
    imp = snap_verbs.add_parser(
        "import", help="replay a snapshot: request missing taps, install each skill through its own "
                       "install path (admin)")
    imp.add_argument("input", help="a snapshot file written by `nerva skills snapshot export`")
    imp.add_argument("--dry-run", action="store_true", help="show the plan; request and install nothing")
    imp.add_argument("--yes", action="store_true", help="go ahead without asking (you read the plan)")
    imp.add_argument("--json", action="store_true")

    diff = skills_verbs.add_parser(
        "diff", help="what you changed in a stock skill (a Hermes catalog install or a Nerva optional "
                     "skill), against its stock copy (offline, same data root)")
    diff.add_argument("name", help="the skill's folder, slug or <category>/<skill>")
    diff.add_argument("--no-color", action="store_true")
    diff.add_argument("--json", action="store_true")

    # H024 — find, check, update and reset (Hermes's skills search/check/update/list-modified/reset).
    search = skills_verbs.add_parser(
        "search", help="search every active skill source (the catalog, the import pin, your approved taps)")
    search.add_argument("query", nargs="?", default="", help="text in the slug or description")
    search.add_argument("--tap", default="", help="only this source (a tap id, hermes-catalog or hermes)")
    search.add_argument("--limit", "-n", type=int, default=40, help=f"at most this many rows (1-{SEARCH_MAX})")
    search.add_argument("--json", action="store_true")
    check = skills_verbs.add_parser(
        "check", help="installed pinned skills whose source has moved to another commit since the install")
    check.add_argument("--json", action="store_true")
    update = skills_verbs.add_parser(
        "update", help="bring catalog skills up to this hub's catalog commit (admin; your edits are kept "
                       "and refuse the update)")
    update.add_argument("names", nargs="*", metavar="name", help="catalog skills to update (default: all "
                                                                  "that `nerva skills check` lists)")
    update.add_argument("--force", action="store_true",
                        help="also replace files you edited and restore files you deleted (a copy of each "
                             "edited file is kept on the hub)")
    update.add_argument("--json", action="store_true")
    modified = skills_verbs.add_parser(
        "list-modified", help="stock skills you edited (catalog and optional installs; offline, same data root)")
    modified.add_argument("--json", action="store_true")
    for verb, text in (("install", "install one skill from a skill source through its owner install route "
                                   "(admin; it lands quarantined, read as data until you vouch for it)"),
                       ("inspect", "everything a source says about one skill before you install it")):
        one = skills_verbs.add_parser(verb, help=text)
        one.add_argument("skill", help="the skill's slug as `nerva skills search` shows it")
        one.add_argument("--from", dest="source", default="",
                         help="the source (a tap id, hermes-catalog or hermes) when several list it")
        one.add_argument("--json", action="store_true")
    reset = skills_verbs.add_parser(
        "reset", help="put a catalog skill back to stock, replacing your edits (a copy of each is kept on "
                      "the hub; admin) — `nerva skills catalog repair NAME --force`")
    reset.add_argument("skill", help="<category>/<skill> or the slug")
    reset.add_argument("--yes", action="store_true", help="go ahead without asking")
    reset.add_argument("--json", action="store_true")


VERBS = ("tap", "snapshot", "diff", "search", "check", "update", "list-modified", "reset", "install", "inspect")


def run(ns: argparse.Namespace, ctx) -> int:
    if ns.action == "tap":
        return _tap(ns, ctx)
    if ns.action == "snapshot":
        return _export(ns, ctx) if ns.snapshot_action == "export" else _import(ns, ctx)
    if ns.action == "search":
        return _search(ns, ctx)
    if ns.action in ("check", "update"):
        return _check(ns, ctx)
    if ns.action == "list-modified":
        return _list_modified(ns, ctx)
    if ns.action == "reset":
        return _reset(ns, ctx)
    if ns.action in ("install", "inspect"):
        return _install_or_inspect(ns, ctx)
    return _diff(ns, ctx)


# ── taps ────────────────────────────────────────────────────────────────────────

def _tap_ident(raw: str) -> str | None:
    from agents.core.skills import taps

    value = raw.strip()
    if "/" in value:
        if not taps.valid_repo(value):
            return None
        value = taps.tap_id(value)
    return value if _TAP_ID.fullmatch(value) else None


def _tap_rows(reply: Any) -> list[Mapping]:
    rows = reply.get("taps") if isinstance(reply, Mapping) else None
    return [row for row in rows[:200] if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _tap(ns: argparse.Namespace, ctx) -> int:
    from agents.core.skills import taps

    from .nerva import EXIT_FAILED, EXIT_OK, EXIT_USAGE

    action = ns.tap_action
    if action == "list":
        reply = ctx.client().get(TAPS)
        rows = _tap_rows(reply)
        if ns.json:
            _dump(ctx, {"taps": rows})
            return EXIT_OK
        if not rows:
            ctx.err.write("unexpected reply from the hub: no skill sources listed\n")
            return EXIT_FAILED
        for row in rows:
            where = f"{_plain(row.get('repo'), 80)}@{_plain(str(row.get('commit') or '')[:8], 8)}"
            if row.get("path"):
                where += f" {_plain(row.get('path'), 60)}"
            skills = row.get("skills")
            count = f"{skills} skills" if type(skills) is int else ""
            ctx.say(f"  {_plain(row.get('id'), 60):<32} {_plain(row.get('trust'), 10):<9} "
                    f"{_plain(row.get('status'), 12):<11} {where} {count}".rstrip())
        if not any(not row.get("builtin") for row in rows):
            ctx.say("no taps of your own; add one: nerva skills tap add owner/repo --commit <sha>")
        return EXIT_OK
    if action == "add":
        if not taps.valid_repo(ns.repo):
            ctx.err.write("repo must be owner/repo\n")
            return EXIT_USAGE
        if not _SHA40.fullmatch(ns.commit or ""):
            ctx.err.write("--commit must be an exact 40-hex commit (lowercase); branches and tags move\n")
            return EXIT_USAGE
        if not taps.valid_path(ns.path):
            ctx.err.write("--path must be a relative folder like skills or packs/skills\n")
            return EXIT_USAGE
        reply = ctx.client().post(TAPS, {"repo": ns.repo, "commit": ns.commit, "path": ns.path,
                                         "trust": ns.trust})
        if not isinstance(reply, Mapping) or reply.get("status") != "pending_approval":
            ctx.err.write("unexpected reply from the hub: the request was not confirmed\n")
            return EXIT_FAILED
        if ns.json:
            _dump(ctx, reply)
            return EXIT_OK
        ident = taps.tap_id(ns.repo)
        ctx.say(f"approval pending #{_plain(reply.get('task_id'), 20)}: trust {ns.repo}@{ns.commit[:8]} "
                f"({ns.trust}) as a skill source")
        ctx.say("  accept it in the owner inbox or `nerva approvals list`, then "
                f"`nerva skills tap refresh {ident}`")
        return EXIT_OK
    ident = _tap_ident(ns.tap)
    if ident is None:
        ctx.err.write("give a tap id (owner--repo) or owner/repo\n")
        return EXIT_USAGE
    if action == "remove":
        reply = ctx.client().request("DELETE", f"{TAPS}/{quote(ident, safe='')}")
        if not isinstance(reply, Mapping) or reply.get("ok") is not True:
            ctx.err.write("unexpected reply from the hub: the removal was not confirmed\n")
            return EXIT_FAILED
        if ns.json:
            _dump(ctx, reply)
        else:
            ctx.say(f"removed tap {ident}; skills installed from it stay installed")
        return EXIT_OK
    reply = ctx.client().post(f"{TAPS}/{quote(ident, safe='')}/refresh", {})
    if not isinstance(reply, Mapping):
        ctx.err.write("unexpected reply from the hub\n")
        return EXIT_FAILED
    if ns.json:
        _dump(ctx, reply)
        return EXIT_OK
    tap = reply.get("tap") if isinstance(reply.get("tap"), Mapping) else reply
    ctx.say(f"{ident}: {_plain(tap.get('skills'), 10)} installable skills, "
            f"{_plain(tap.get('refused'), 10)} refused" + (" (index truncated)" if tap.get("truncated") else ""))
    return EXIT_OK


# ── snapshot export ─────────────────────────────────────────────────────────────

def _entry_parts(source_path: Any) -> tuple[str, str] | None:
    """``(folder, slug)`` from a recorded ``<folder>/<slug>/SKILL.md``."""
    from agents.core.skills import taps

    if not isinstance(source_path, str) or not source_path.endswith("/SKILL.md"):
        return None
    parent = source_path[: -len("/SKILL.md")]
    if not taps.valid_path(parent, max_parts=10):
        return None
    pure = PurePosixPath(parent)
    if len(pure.parts) < 2 or not _SLUG.fullmatch(pure.name):
        return None
    return pure.parent.as_posix(), pure.name


def _skill_record(manifest: Mapping) -> tuple[dict | None, str]:
    """One snapshot row for an installed skill's manifest, or ``(None, why)``."""
    from agents.core.skills import hermes_catalog, taps

    name = manifest.get("name")
    commit = manifest.get("source_commit")
    sha = manifest.get("content_sha256")
    path = manifest.get("source_path")
    if manifest.get("source") == OPTIONAL_SOURCE:
        slug = PurePosixPath(path).parent.name if isinstance(path, str) else ""
        if not (isinstance(path, str) and path == f"optional-skills/{slug}/SKILL.md"
                and _OPTIONAL_SLUG.fullmatch(slug) and isinstance(sha, str) and _SHA64.fullmatch(sha)):
            return None, "its recorded optional-skill source is not valid"
        return {"name": slug, "kind": "optional", "slug": slug, "content_sha256": sha}, ""
    if not (isinstance(commit, str) and _SHA40.fullmatch(commit) and isinstance(sha, str)
            and _SHA64.fullmatch(sha) and isinstance(path, str)):
        return None, "no pinned source (a local import or your own skill)"
    parts = _entry_parts(path)
    if parts is None:
        return None, "its recorded source path is not a skill folder"
    folder, slug = parts
    clean = _plain(name, 128) if isinstance(name, str) else slug
    if manifest.get("source") == hermes_catalog.INSTALL_SOURCE and manifest.get("source_catalog") == "vendored":
        return {"name": clean, "kind": "catalog", "identifier": f"{folder}/{slug}", "slug": slug,
                "commit": commit, "content_sha256": sha}, ""
    repo = manifest.get("source_repository")
    if not taps.valid_repo(repo):
        return None, "no pinned source repository"
    tap = taps.BUILTIN_PIN if manifest.get("source") == taps.BUILTIN_PIN else taps.tap_id(repo)
    return {"name": clean, "kind": "tap", "tap": tap, "repo": repo, "path": folder, "slug": slug,
            "commit": commit, "content_sha256": sha}, ""


def build_snapshot(imported_reply: Any, taps_reply: Any, *, now: float | None = None) -> dict:
    """The snapshot of what the hub reports installed (pure: no I/O)."""
    from agents.core.skills import taps

    manifests = imported_reply.get("imported") if isinstance(imported_reply, Mapping) else None
    skills, skipped = [], []
    for manifest in (manifests if isinstance(manifests, list) else [])[:5000]:
        if not isinstance(manifest, Mapping):
            continue
        row, why = _skill_record(manifest)
        if row is None:
            skipped.append({"name": _plain(manifest.get("name"), 128), "why": why})
        elif not any(s["kind"] == row["kind"] and s["slug"] == row["slug"]
                     and s.get("tap") == row.get("tap") for s in skills):
            skills.append(row)
    tap_rows: dict[str, dict] = {}
    for row in _tap_rows(taps_reply):
        if row.get("builtin") or row.get("status") != "active":
            continue
        repo, commit, path = row.get("repo"), row.get("commit"), row.get("path")
        if (taps.valid_repo(repo) and isinstance(commit, str) and _SHA40.fullmatch(commit)
                and taps.valid_path(path) and row.get("trust") in taps.OWNER_TRUST):
            tap_rows[taps.tap_id(repo)] = {"id": taps.tap_id(repo), "repo": repo, "commit": commit,
                                           "path": path, "trust": row["trust"]}
    for skill in skills:
        if skill["kind"] != "tap" or skill["tap"] == taps.BUILTIN_PIN or skill["tap"] in tap_rows:
            continue
        if taps.valid_path(skill["path"]):
            # The tap was removed after the install: its pin is still the skill's source.
            tap_rows[skill["tap"]] = {"id": skill["tap"], "repo": skill["repo"], "commit": skill["commit"],
                                      "path": skill["path"], "trust": "community"}
    stamp = time.gmtime(time.time() if now is None else now)
    return {"format": SNAPSHOT_FORMAT, "version": SNAPSHOT_VERSION,
            "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", stamp),
            "skills": sorted(skills, key=lambda s: (s["kind"], s.get("tap", ""), s["slug"]))[:MAX_SNAPSHOT_SKILLS],
            "taps": sorted(tap_rows.values(), key=lambda t: t["id"])[:MAX_SNAPSHOT_TAPS],
            "not_exported": skipped[:MAX_SNAPSHOT_SKILLS]}


def _write_private(target: Path, text: str) -> None:
    """Replace ``target`` (a regular file or nothing) atomically, mode 0600, never through a
    linked folder on the way and with the bytes on disk before the rename."""
    parent = target.parent if str(target.parent) else Path(".")
    if os.path.realpath(parent) != os.path.abspath(parent):
        raise OSError(f"{parent} is reached through a link; give the real folder")
    try:
        info = os.lstat(target)
    except FileNotFoundError:
        info = None
    if info is not None and not stat.S_ISREG(info.st_mode):
        raise OSError(f"{target} exists and is not a regular file")
    fd, tmp = tempfile.mkstemp(prefix=".nerva-snapshot-", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _export(ns: argparse.Namespace, ctx) -> int:
    from .nerva import EXIT_FAILED, EXIT_OK

    client = ctx.client()
    snapshot = build_snapshot(client.get(IMPORTED), client.get(TAPS))
    text = json.dumps(snapshot, indent=2, ensure_ascii=True) + "\n"
    if ns.output == "-":
        ctx.out.write(text)
        return EXIT_OK
    try:
        _write_private(Path(ns.output), text)
    except OSError as exc:
        ctx.err.write(f"could not write {_plain(ns.output, 200)}: {_plain(exc.strerror or exc, 200)}\n")
        return EXIT_FAILED
    ctx.say(f"snapshot written: {_plain(ns.output, 200)}")
    ctx.say(f"  {len(snapshot['skills'])} skill(s), {len(snapshot['taps'])} tap(s)")
    for row in snapshot["not_exported"][:20]:
        ctx.say(f"  not exported: {row['name']} — {row['why']}")
    if len(snapshot["not_exported"]) > 20:
        ctx.say(f"  … and {len(snapshot['not_exported']) - 20} more not exported")
    return EXIT_OK


# ── snapshot import ─────────────────────────────────────────────────────────────

class SnapshotError(ValueError):
    pass


class FileTooLarge(OSError):
    """A regular file over the read bound."""


def read_regular_file(path: str, limit: int) -> bytes:
    """At most ``limit`` bytes of a regular file, opened without following a final link and
    without blocking on a FIFO; anything else raises :class:`OSError`."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode):
        raise OSError(f"{path} is not a regular file")
    fd = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(f"{path} is not a regular file")
        chunks, size = [], 0
        while size <= limit:
            piece = os.read(fd, min(65536, limit + 1 - size))
            if not piece:
                break
            chunks.append(piece)
            size += len(piece)
    finally:
        os.close(fd)
    data = b"".join(chunks)
    if len(data) > limit:
        raise FileTooLarge(f"{path} is larger than {limit} bytes")
    return data


def parse_snapshot(raw: bytes) -> dict:
    """The validated snapshot; :class:`SnapshotError` names the first problem."""
    from agents.core.skills import taps

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise SnapshotError("not a JSON snapshot") from exc
    if not isinstance(data, dict) or data.get("format") != SNAPSHOT_FORMAT:
        raise SnapshotError("not a nerva skills snapshot")
    if data.get("version") != SNAPSHOT_VERSION:
        raise SnapshotError(f"snapshot version {_plain(data.get('version'), 10)} is not supported")
    skills, tap_rows = data.get("skills"), data.get("taps", [])
    if not isinstance(skills, list) or not isinstance(tap_rows, list):
        raise SnapshotError("skills and taps must be lists")
    if len(skills) > MAX_SNAPSHOT_SKILLS or len(tap_rows) > MAX_SNAPSHOT_TAPS:
        raise SnapshotError(f"at most {MAX_SNAPSHOT_SKILLS} skills and {MAX_SNAPSHOT_TAPS} taps")
    out_taps = []
    for row in tap_rows:
        if not (isinstance(row, dict) and taps.valid_repo(row.get("repo"))
                and isinstance(row.get("commit"), str) and _SHA40.fullmatch(row["commit"])
                and taps.valid_path(row.get("path")) and row.get("trust") in taps.OWNER_TRUST):
            raise SnapshotError("a tap entry is not owner/repo, an exact commit, a path and a trust")
        ident = taps.tap_id(row["repo"])
        if ident in (taps.BUILTIN_CATALOG, taps.BUILTIN_PIN) or any(t["id"] == ident for t in out_taps):
            raise SnapshotError(f"tap {ident} is reserved or listed twice")
        out_taps.append({"id": ident, "repo": row["repo"], "commit": row["commit"], "path": row["path"],
                         "trust": row["trust"]})
    out_skills = []
    for row in skills:
        if not isinstance(row, dict) or row.get("kind") not in ("catalog", "tap", "optional"):
            raise SnapshotError("a skill entry has no kind (catalog, tap or optional)")
        slug, commit, sha = row.get("slug"), row.get("commit"), row.get("content_sha256")
        if row["kind"] == "optional":
            if not (isinstance(slug, str) and _OPTIONAL_SLUG.fullmatch(slug) and isinstance(sha, str)
                    and _SHA64.fullmatch(sha)):
                raise SnapshotError("an optional skill entry needs a slug and a sha256")
            if any(s["kind"] == "optional" and s["slug"] == slug for s in out_skills):
                raise SnapshotError(f"optional skill {slug} is listed twice")
            out_skills.append({"kind": "optional", "name": slug, "slug": slug, "commit": "",
                               "content_sha256": sha})
            continue
        if not (isinstance(slug, str) and _SLUG.fullmatch(slug) and isinstance(commit, str)
                and _SHA40.fullmatch(commit) and isinstance(sha, str) and _SHA64.fullmatch(sha)):
            raise SnapshotError("a skill entry needs a slug, an exact commit and a sha256")
        name = row.get("name") if isinstance(row.get("name"), str) and _NAME.fullmatch(row["name"]) else slug
        if row["kind"] == "catalog":
            ident = row.get("identifier")
            if not (taps.valid_path(ident, max_parts=10) and PurePosixPath(ident).name == slug):
                raise SnapshotError(f"catalog skill {slug} has no catalog path")
            out_skills.append({"kind": "catalog", "name": name, "slug": slug, "identifier": ident,
                               "commit": commit, "content_sha256": sha})
            continue
        tap = row.get("tap")
        if tap == taps.BUILTIN_PIN:
            out_skills.append({"kind": "tap", "name": name, "slug": slug, "tap": tap, "repo": None,
                               "commit": commit, "content_sha256": sha})
            continue
        if not (isinstance(tap, str) and any(t["id"] == tap for t in out_taps)):
            raise SnapshotError(f"skill {slug} names a tap the snapshot does not list")
        source = next(t for t in out_taps if t["id"] == tap)
        if source["commit"] != commit:
            raise SnapshotError(f"skill {slug} and its tap {tap} name different commits")
        out_skills.append({"kind": "tap", "name": name, "slug": slug, "tap": tap, "repo": source["repo"],
                           "commit": commit, "content_sha256": sha})
    return {"skills": out_skills, "taps": out_taps}


def _installed(imported_reply: Any) -> set[tuple[str, str]]:
    """``(content_sha256, source_commit)`` of every installed pinned skill; a Nerva optional
    skill (no commit) counts as ``(content_sha256, "")``."""
    manifests = imported_reply.get("imported") if isinstance(imported_reply, Mapping) else None
    found = set()
    for manifest in (manifests if isinstance(manifests, list) else [])[:5000]:
        if isinstance(manifest, Mapping):
            sha, commit = manifest.get("content_sha256"), manifest.get("source_commit")
            if manifest.get("source") == OPTIONAL_SOURCE:
                commit = ""
            if isinstance(sha, str) and isinstance(commit, str):
                found.add((sha, commit))
    return found


def _installed_optional(imported_reply: Any) -> set[str]:
    """Folder names of the Nerva optional skills installed (any version)."""
    manifests = imported_reply.get("imported") if isinstance(imported_reply, Mapping) else None
    found = set()
    for manifest in (manifests if isinstance(manifests, list) else [])[:5000]:
        if isinstance(manifest, Mapping) and manifest.get("source") == OPTIONAL_SOURCE:
            path = manifest.get("source_path")
            if isinstance(path, str):
                found.add(PurePosixPath(path).parent.name)
    return found


def _shipped_optional(reply: Any) -> dict[str, str]:
    """``{name: SKILL.md sha256}`` of the optional skills this hub ships (when it says)."""
    rows = reply.get("skills") if isinstance(reply, Mapping) else None
    out = {}
    for row in (rows if isinstance(rows, list) else [])[:200]:
        if isinstance(row, Mapping) and isinstance(row.get("name"), str):
            sha = row.get("content_sha256")
            if isinstance(sha, str) and _SHA64.fullmatch(sha):
                out[row["name"]] = sha
    return out


def plan_import(snapshot: dict, taps_reply: Any, imported_reply: Any, optional_reply: Any = None) -> dict:
    """What an import would do, decided from the hub's current state (pure)."""
    shipped = _shipped_optional(optional_reply)
    hub_taps = {str(row.get("id")): row for row in _tap_rows(taps_reply)}
    installed = _installed(imported_reply)
    optional_present = _installed_optional(imported_reply)
    tap_steps, skill_steps = [], []
    for tap in snapshot["taps"]:
        row = hub_taps.get(tap["id"])
        if row is None:
            step = "request"
        elif row.get("commit") != tap["commit"]:
            step = "conflict"
        else:
            step = "present" if row.get("status") == "active" else "awaiting_approval"
        tap_steps.append({**tap, "step": step})
    tap_state = {t["id"]: t["step"] for t in tap_steps}
    catalog = hub_taps.get("hermes-catalog") or {}
    pin = hub_taps.get("hermes") or {}
    for skill in snapshot["skills"]:
        step, why = "install", ""
        if (skill["content_sha256"], skill["commit"]) in installed:
            step = "installed"
        elif skill["kind"] == "optional":
            if skill["slug"] in optional_present:
                step, why = "skip", "installed here already, at this hub's own shipped version"
            elif skill["slug"] in shipped and shipped[skill["slug"]] != skill["content_sha256"]:
                # Installing would write other bytes than the snapshot names: refused up front.
                step, why = "mismatch", "this hub ships another version of it than the snapshot's"
        elif skill["kind"] == "catalog":
            if catalog.get("status") != "active":
                step, why = "skip", "the vendored catalog is unavailable on this hub"
            elif catalog.get("commit") != skill["commit"]:
                step, why = "skip", (f"this hub's catalog is @{_plain(str(catalog.get('commit'))[:8], 8)}, "
                                     f"the snapshot's @{skill['commit'][:8]}")
        elif skill["tap"] == "hermes":
            if pin.get("status") != "active" or pin.get("commit") != skill["commit"]:
                step, why = "skip", "this hub's built-in import pin is at another commit"
        else:
            state = tap_state.get(skill["tap"])
            if state == "conflict":
                step, why = "skip", f"tap {skill['tap']} is at another commit on this hub"
            elif state != "present":
                step, why = "wait", f"tap {skill['tap']} needs your approval card, then a refresh"
        skill_steps.append({**skill, "step": step, "why": why})
    return {"taps": tap_steps, "skills": skill_steps}


def _say_plan(ctx, plan: dict) -> None:
    say = ctx.say
    _say_plan_to(say, plan)


def _say_plan_to(say, plan: dict) -> None:
    for tap in plan["taps"]:
        word = {"request": "request a card for", "present": "already trusted:", "conflict": "CONFLICT:",
                "awaiting_approval": "card already pending for"}[tap["step"]]
        extra = " (this hub trusts it at another commit; left as it is)" if tap["step"] == "conflict" else ""
        say(f"  tap   {word} {tap['repo']}@{tap['commit'][:8]} {tap['path']} ({tap['trust']}){extra}")
    for skill in plan["skills"]:
        why = f" — {skill['why']}" if skill["why"] else ""
        if skill["kind"] == "optional":
            say(f"  skill {skill['step']:<9} {skill['slug']} from Nerva's optional skills{why}")
            continue
        source = "catalog" if skill["kind"] == "catalog" else skill["tap"]
        say(f"  skill {skill['step']:<9} {skill['slug']} from {source}@{skill['commit'][:8]}{why}")


def _ask(ctx, prompt: str, refusal: str) -> bool:
    """A yes/no question on the terminal; the prompt goes to stderr so stdout stays data."""
    isatty = getattr(ctx.inp, "isatty", None)
    if not (callable(isatty) and isatty()):
        ctx.err.write(refusal + "\n")
        return False
    ctx.err.write(prompt)
    ctx.err.flush()
    answer = ctx.inp.readline(16)
    return answer.strip().lower() in ("y", "yes")


def _confirm(ctx, ns: argparse.Namespace) -> bool:
    if ns.yes:
        return True
    return _ask(ctx, "Go ahead? [y/N] ", "not a terminal: re-run with --yes to go ahead (you read the plan)")


def _import(ns: argparse.Namespace, ctx) -> int:
    from .client import HubError
    from .nerva import EXIT_FAILED, EXIT_OK, EXIT_USAGE

    try:
        snapshot = parse_snapshot(read_regular_file(ns.input, MAX_SNAPSHOT_BYTES))
    except OSError as exc:
        ctx.err.write(f"cannot read {_plain(ns.input, 200)}: {_plain(exc.strerror or exc, 200)}\n")
        return EXIT_USAGE
    except SnapshotError as exc:
        ctx.err.write(f"{_plain(ns.input, 200)}: {_plain(exc, 300)}\n")
        return EXIT_USAGE
    client = ctx.client()
    optional_reply = None
    if any(skill["kind"] == "optional" for skill in snapshot["skills"]):
        try:
            optional_reply = client.get(OPTIONAL_CATALOG)
        except HubError:
            optional_reply = None          # an older hub: the check after the install still runs
    plan = plan_import(snapshot, client.get(TAPS), client.get(IMPORTED), optional_reply)
    if not ns.json:
        ctx.say(f"snapshot: {len(snapshot['skills'])} skill(s), {len(snapshot['taps'])} tap(s)")
        _say_plan(ctx, plan)
    if ns.dry_run:
        if ns.json:
            _dump(ctx, {"dry_run": True, **plan})
        return EXIT_OK
    acting = any(t["step"] == "request" for t in plan["taps"]) or any(
        s["step"] == "install" for s in plan["skills"])
    if acting and not ns.yes and ns.json:
        # stdout carries only the JSON result: the plan and the question go to stderr.
        ctx.err.write(f"snapshot: {len(snapshot['skills'])} skill(s), {len(snapshot['taps'])} tap(s)\n")
        _say_plan_to(lambda line: ctx.err.write(line + "\n"), plan)
    if acting and not _confirm(ctx, ns):
        return EXIT_FAILED
    results = {"taps": [], "skills": []}
    failed = 0
    for tap in plan["taps"]:
        outcome = {"id": tap["id"], "step": tap["step"]}
        if tap["step"] == "request":
            try:
                reply = client.post(TAPS, {"repo": tap["repo"], "commit": tap["commit"], "path": tap["path"],
                                           "trust": tap["trust"]})
                outcome.update(result="card", task_id=reply.get("task_id") if isinstance(reply, Mapping) else None)
            except HubError as exc:
                failed += 1
                outcome.update(result="failed", reason=_plain(exc.reason, 200))
        results["taps"].append(outcome)
    for skill in plan["skills"]:
        outcome = {"slug": skill["slug"], "step": skill["step"], "why": skill["why"]}
        if skill["step"] == "mismatch":
            failed += 1
            outcome.update(result="mismatch", reason=skill["why"])
        if skill["step"] == "install":
            if skill["kind"] == "optional":
                path, body = OPTIONAL_INSTALL, {"name": skill["slug"]}
            elif skill["kind"] == "catalog":
                path, body = CATALOG_INSTALL, {"skill": skill["identifier"]}
            else:
                path, body = TAP_INSTALL, {"tap": skill["tap"], "skill": skill["slug"]}
            try:
                reply = client.post(path, body)
                ok = isinstance(reply, Mapping) and (
                    reply.get("status") == "installed_review_required" if skill["kind"] == "optional"
                    else reply.get("ok") is True)
                outcome["result"] = "installed" if ok else "failed"
                failed += 0 if ok else 1
            except HubError as exc:
                failed += 1
                outcome.update(result="failed", reason=_plain(exc.reason, 200))
        results["skills"].append(outcome)
    # Verify what the hub now holds against the snapshot's bytes (sha256 of SKILL.md at that commit).
    installed = _installed(client.get(IMPORTED))
    for skill, outcome in zip(plan["skills"], results["skills"], strict=True):
        if outcome.get("result") == "installed" and (skill["content_sha256"], skill["commit"]) not in installed:
            failed += 1
            outcome.update(result="mismatch", reason="the installed SKILL.md is not the snapshot's")
    if ns.json:
        _dump(ctx, {**results, "failed": failed})
    else:
        for outcome in results["taps"]:
            if outcome.get("result") == "card":
                ctx.say(f"  tap {outcome['id']}: approval pending #{_plain(outcome.get('task_id'), 20)}")
            elif outcome.get("result") == "failed":
                ctx.say(f"  tap {outcome['id']}: failed — {outcome['reason']}")
        for outcome in results["skills"]:
            if "result" in outcome:
                reason = f" — {outcome['reason']}" if outcome.get("reason") else ""
                ctx.say(f"  skill {outcome['slug']}: {outcome['result']}{reason}")
        counts = {key: sum(1 for o in results["skills"] if o.get("result", o["step"]) == key)
                  for key in ("installed", "wait", "skip")}
        ctx.say(f"done: {counts['installed']} installed, {counts['wait']} waiting for a tap, "
                f"{counts['skip']} skipped, {failed} failed")
        if counts["wait"]:
            ctx.say("  accept the tap cards, run `nerva skills tap refresh <id>`, then import again")
        if counts["installed"]:
            ctx.say("  installed skills are imported: their text is read as data until you vouch for them")
    return EXIT_FAILED if failed else EXIT_OK


# ── diff ────────────────────────────────────────────────────────────────────────

def _linked_component(root: Path, rel: str) -> bool:
    parts = PurePosixPath(rel).parts
    return any(root.joinpath(*parts[: i + 1]).is_symlink() for i in range(len(parts)))


def _local_files(root: Path) -> tuple[dict[str, str], bool]:
    """``{rel: "file"|"other"}`` under ``root`` without following links. Bounded: at most
    ``MAX_DIFF_ENTRIES`` directory entries are looked at in all (files, folders and anything
    else count), ``MAX_DIFF_FILES`` are kept and folders deeper than ``MAX_DIFF_DEPTH`` are not
    entered; anything cut sets ``truncated``."""
    found: dict[str, str] = {}
    truncated = False
    budget = MAX_DIFF_ENTRIES
    stack = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            with os.scandir(current) as iterator:
                entries = list(itertools.islice(iterator, budget + 1))
        except OSError:
            continue
        if len(entries) > budget:
            entries, truncated = entries[:budget], True
        budget -= len(entries)
        for entry in sorted(entries, key=lambda e: e.name):
            rel = Path(entry.path).relative_to(root).as_posix()
            try:
                if entry.is_dir(follow_symlinks=False):
                    if depth + 1 < MAX_DIFF_DEPTH:
                        stack.append((Path(entry.path), depth + 1))
                    else:
                        truncated = True
                    continue
                kind = "file" if entry.is_file(follow_symlinks=False) else "other"
            except OSError:
                kind = "other"
            if len(found) >= MAX_DIFF_FILES:
                return found, True
            found[rel] = kind
        if budget <= 0 and stack:
            return found, True
    return found, truncated


#: Top-level names an install writes for the hub's own records, never part of a skill.
_CONTROL_TOP = frozenset({"manifest.json", "SKILL.sig", "PENDING_REVIEW", "EXTERNAL_SOURCE",
                          "OWNER_APPROVED_IN_PROCESS"})
MAX_SIDECAR_BYTES = 64 * 1024


def _sidecar(target: Path) -> dict | None:
    """The install's ``manifest.json`` when it is a plain, bounded JSON object; else None."""
    try:
        data = json.loads(read_regular_file(str(target / "manifest.json"), MAX_SIDECAR_BYTES).decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _recorded_catalog_files(record: Mapping) -> dict[str, str]:
    """``{rel: sha256}`` the catalog install recorded (the paths ``file_state`` honours)."""
    from agents.core.skills import hermes_catalog

    out: dict[str, str] = {}
    for item in record.get("source_files") or []:
        rel = item.get("path") if isinstance(item, Mapping) else None
        sha = item.get("sha256") if isinstance(item, Mapping) else None
        if (isinstance(rel, str) and isinstance(sha, str)
                and (rel == "SKILL.md" or hermes_catalog.safe_extra_path(rel))):
            out[rel] = sha
    return out


def _baseline(skills_dir: Path, ident: str, catalog_root: Path | None,
              optional_root: Path | None) -> dict:
    """What the install of ``ident`` recorded, and the stock copy as it is today.

    ``{"ok": True, "slug", "source", "target", "recorded": {rel: sha256}, "complete": bool,
    "stock": {rel: bytes} | None, "commit", "installed_commit"}`` — ``recorded`` is what the
    install wrote (for a catalog install, its ``source_files``; for a Nerva optional skill, its
    SKILL.md ``content_sha256``, plus every shipped file when the shipped copy is still the one
    it was installed from); ``complete`` says the record covers every file the install wrote."""
    from agents.core.paths import app_root
    from agents.core.skills import hermes_catalog
    from agents.core.skills.signing import SkillSourceSnapshotError, source_snapshot

    reason = ""
    try:
        catalog = hermes_catalog.load(catalog_root)
    except hermes_catalog.CatalogError:
        catalog, reason = None, "the vendored Hermes catalog does not match its manifest"
    entry = hermes_catalog.resolve(catalog, ident) if catalog is not None else None
    if entry is not None:
        target = Path(skills_dir) / entry["slug"]
        record = hermes_catalog.catalog_record(target, entry)
        if record is not None:
            try:
                stock = hermes_catalog.verified_files(catalog, entry)
            except hermes_catalog.CatalogError:
                stock = None
            return {"ok": True, "slug": entry["slug"], "source": "hermes-catalog", "target": target,
                    "recorded": _recorded_catalog_files(record), "complete": True, "stock": stock,
                    "commit": catalog.commit, "installed_commit": str(record.get("source_commit") or "")}
    name = str(ident or "").strip().strip("/")
    if _OPTIONAL_SLUG.fullmatch(name):
        target = Path(skills_dir) / name
        data = _sidecar(target) if not target.is_symlink() and target.is_dir() else None
        sha = data.get("content_sha256") if data else None
        if (data and data.get("imported") is True and data.get("source") == OPTIONAL_SOURCE
                and data.get("source_path") == f"optional-skills/{name}/SKILL.md"):
            if not (isinstance(sha, str) and _SHA64.fullmatch(sha)):
                return {"ok": False, "reason": "this optional skill's install recorded no SKILL.md digest"}
            stock, fingerprint = None, None
            stock_dir = Path(optional_root or app_root() / "optional-skills") / name
            if not stock_dir.is_symlink() and stock_dir.is_dir():
                try:
                    snapshot = source_snapshot(stock_dir)
                    fingerprint = snapshot.fingerprint
                    stock = {item.relative_path: item.content for item in snapshot.files
                             if item.kind == "file"
                             and "__pycache__" not in PurePosixPath(item.relative_path).parts}
                except (SkillSourceSnapshotError, OSError):
                    stock = None
            recorded, complete = {"SKILL.md": sha}, False
            if stock is not None and fingerprint and fingerprint == data.get("source_fingerprint"):
                # The shipped copy is the very snapshot this skill was installed from.
                recorded, complete = {rel: _sha(body) for rel, body in stock.items()}, True
            return {"ok": True, "slug": name, "source": OPTIONAL_SOURCE, "target": target,
                    "recorded": recorded, "complete": complete, "stock": stock, "commit": "",
                    "installed_commit": ""}
    if entry is not None:
        target = Path(skills_dir) / entry["slug"]
        if not target.exists() and not target.is_symlink():
            return {"ok": False, "reason": "this catalog skill is not installed"}
        return {"ok": False, "reason": "this folder was not written by a catalog install of that skill"}
    return {"ok": False, "reason": reason or (
        "not a stock skill: diff compares a Hermes catalog install or a Nerva optional skill "
        "with what its install wrote")}


def diff_installed_skill(skills_dir: Path, ident: str, *, catalog_root: Path | None = None,
                         optional_root: Path | None = None) -> dict:
    """The owner's edits to a stock skill they installed, judged as the hub judges them
    (``hermes_catalog.file_state``): against what the install *recorded* writing, never against
    a newer stock copy. Changes the stock copy made since the install are reported apart, in
    ``upstream``, and are never shown as edits.

    ``{"ok": True, "skill", "source", "commit", "installed_commit", "modified", "files":
    [{path, status, diff}], "behind", "upstream": [{path, status}], "not_compared", "truncated"}``;
    edit ``status`` is ``modified|added|removed|binary|not_plain|too_large`` (``removed`` is a
    file the owner deleted). A ``modified`` file carries a unified diff when the bytes it was
    installed with are still on this machine (the stock copy has not moved), else ``""``."""
    base = _baseline(skills_dir, ident, catalog_root, optional_root)
    if not base.get("ok"):
        return {"ok": False, "reason": base["reason"]}
    target, recorded, stock = base["target"], base["recorded"], base["stock"]
    local, truncated = _local_files(target)
    for name in _CONTROL_TOP:
        local.pop(name, None)            # the install's own records, not the skill
    for rel in [r for r in local if "__pycache__" in PurePosixPath(r).parts]:
        local.pop(rel)
    files, not_compared = [], []
    for rel in sorted(set(recorded) | set(local)):
        if rel not in recorded:
            if base["complete"]:
                files.append({"path": rel, "status": "added", "diff": ""})
            else:
                not_compared.append(rel)
            continue
        if rel not in local:
            files.append({"path": rel, "status": "removed", "diff": ""})
            continue
        if local[rel] != "file" or _linked_component(target, rel):
            files.append({"path": rel, "status": "not_plain", "diff": ""})
            continue
        try:
            mine = read_regular_file(str(target / rel), MAX_DIFF_FILE_BYTES)
        except FileTooLarge:
            files.append({"path": rel, "status": "too_large", "diff": ""})
            continue
        except OSError:
            files.append({"path": rel, "status": "not_plain", "diff": ""})
            continue
        if hmac.compare_digest(_sha(mine), recorded[rel]):
            continue
        original = stock.get(rel) if stock is not None else None
        if original is None or not hmac.compare_digest(_sha(original), recorded[rel]):
            files.append({"path": rel, "status": "modified", "diff": ""})   # installed bytes gone
            continue
        try:
            old, new = original.decode("utf-8"), mine.decode("utf-8")
        except UnicodeDecodeError:
            files.append({"path": rel, "status": "binary", "diff": ""})
            continue
        lines = difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                     fromfile=f"installed/{rel}", tofile=f"local/{rel}")
        files.append({"path": rel, "status": "modified", "diff": "".join(lines)})
    upstream = []
    if stock is not None:
        compare = set(recorded) | (set(stock) if base["complete"] else set())
        for rel in sorted(compare):
            if rel not in stock:
                upstream.append({"path": rel, "status": "removed_upstream"})
            elif rel not in recorded:
                upstream.append({"path": rel, "status": "added_upstream"})
            elif not hmac.compare_digest(_sha(stock[rel]), recorded[rel]):
                upstream.append({"path": rel, "status": "changed_upstream"})
    behind = bool(upstream) or bool(base["commit"] and base["installed_commit"]
                                     and base["commit"] != base["installed_commit"])
    return {"ok": True, "skill": base["slug"], "source": base["source"], "commit": base["commit"],
            "installed_commit": base["installed_commit"], "modified": bool(files), "files": files,
            "behind": behind, "upstream": upstream, "stock_known": stock is not None,
            "not_compared": not_compared, "truncated": truncated}


_COLOURS = {"+": "\x1b[32m", "-": "\x1b[31m", "@": "\x1b[36m"}
_EDIT_WORDS = {"added": "+ you added {rel}", "removed": "- you deleted {rel}",
               "binary": "~ {rel}: binary file differs from what was installed",
               "not_plain": "! {rel}: not a plain file now (a link or a special file)",
               "too_large": "! {rel}: changed, and now larger than 256 KiB (not shown)"}


def _diff(ns: argparse.Namespace, ctx) -> int:
    from agents.core.skills.loader import _writable_skills_dir

    from .nerva import EXIT_FAILED, EXIT_OK, EXIT_USAGE

    if not ns.name or len(ns.name) > 200:
        ctx.err.write("give the skill's folder, slug or <category>/<skill>\n")
        return EXIT_USAGE
    result = diff_installed_skill(_writable_skills_dir(), ns.name)
    if ns.json:
        _dump(ctx, result)
        return EXIT_OK if result.get("ok") else EXIT_FAILED
    if not result.get("ok"):
        ctx.err.write(f"{_plain(ns.name, 120)}: {result['reason']}\n")
        return EXIT_FAILED
    catalog = result["source"] == "hermes-catalog"
    if not result["modified"]:
        ctx.say(f"{result['skill']}: no local edits — every file is as its install wrote it")
    isatty = getattr(ctx.out, "isatty", None)
    colour = not ns.no_color and callable(isatty) and isatty()
    printed = 0
    for item in result["files"]:
        rel = _plain(item["path"], 200)
        if item["status"] in _EDIT_WORDS:
            ctx.say(_EDIT_WORDS[item["status"]].format(rel=rel))
            continue
        if not item["diff"]:
            ctx.say(f"~ {rel}: you changed it (the bytes it was installed with are no longer on this "
                    "machine, so no line diff)")
            continue
        for line in item["diff"].splitlines():
            if printed >= MAX_DIFF_LINES:
                break
            printed += 1
            text = _plain(line, 1000)
            head = text[:1]
            if colour and head in _COLOURS and not text.startswith(("+++", "---")):
                text = f"{_COLOURS[head]}{text}\x1b[0m"
            ctx.say(text)
    if printed >= MAX_DIFF_LINES:
        ctx.say(f"… diff cut at {MAX_DIFF_LINES} lines")
    for rel in result["not_compared"][:20]:
        ctx.say(f"? {_plain(rel, 200)}: not compared (the install recorded no digest for it)")
    if result.get("truncated"):
        ctx.say(f"(only part of your copy was compared: at most {MAX_DIFF_FILES} files, "
                f"{MAX_DIFF_ENTRIES} entries, {MAX_DIFF_DEPTH} levels)")
    if result["behind"]:
        where = (f"the catalog is @{result['commit'][:8]}, this skill was installed @"
                 f"{result['installed_commit'][:8]}" if catalog else "this install ships another version")
        ctx.say(f"stock has moved on since the install ({where}); {len(result['upstream'])} file(s) "
                "differ upstream — these are not your edits")
        if catalog:
            ctx.say(f"  take it: nerva skills update {result['skill']}")
    if result["modified"] and catalog:
        ctx.say(f"revert with: nerva skills reset {result['skill']} (a copy of each edited file is kept)")
    return EXIT_OK


# ── search, check / update, list-modified, reset (H024) ─────────────────────────

def _search(ns: argparse.Namespace, ctx) -> int:
    from .nerva import EXIT_FAILED, EXIT_OK, EXIT_USAGE

    if not 1 <= ns.limit <= SEARCH_MAX:
        ctx.err.write(f"--limit takes 1 to {SEARCH_MAX}\n")
        return EXIT_USAGE
    if len(ns.query) > 100:
        ctx.err.write("the query is at most 100 characters\n")
        return EXIT_USAGE
    tap = ns.tap.strip()
    if tap and tap not in ("hermes-catalog", "hermes"):
        tap = _tap_ident(tap) or ""
        if not tap:
            ctx.err.write("--tap takes a tap id (owner--repo), owner/repo, hermes-catalog or hermes\n")
            return EXIT_USAGE
    query = {"q": ns.query, "limit": ns.limit}
    if tap:
        query["tap"] = tap
    reply = ctx.client().get(f"{TAP_SEARCH}?{urlencode(query)}")
    rows = reply.get("results") if isinstance(reply, Mapping) else None
    if not isinstance(rows, list):
        ctx.err.write("unexpected reply from the hub: no results list\n")
        return EXIT_FAILED
    rows = [row for row in rows[:SEARCH_MAX] if isinstance(row, Mapping)]
    if ns.json:
        _dump(ctx, {"query": ns.query, "matched": reply.get("matched"), "results": rows})
        return EXIT_OK
    matched = reply.get("matched")
    ctx.say(f"{matched if type(matched) is int else len(rows)} match(es); showing {len(rows)}")
    for row in rows:
        mark = "install" if row.get("installable") else "refused"
        line = (f"  {mark:<8} {_plain(row.get('tap'), 40):<24} {_plain(row.get('trust'), 10):<9} "
                f"{_plain(row.get('slug'), 64):<28} {_plain(row.get('description'), 80)}")
        ctx.say(line.rstrip())
        if not row.get("installable") and row.get("reason"):
            ctx.say(f"           why: {_plain(row.get('reason'), 120)}")
    if rows:
        ctx.say("install: nerva skills catalog install <skill> (catalog) or through the HUD's skill "
                "import (taps and the pin)")
    return EXIT_OK


def stale_skills(imported_reply: Any, taps_reply: Any) -> list[dict]:
    """Installed pinned skills whose source now names another commit (pure)."""
    from agents.core.skills import hermes_catalog, taps

    hub_taps = {str(row.get("id")): row for row in _tap_rows(taps_reply)}
    manifests = imported_reply.get("imported") if isinstance(imported_reply, Mapping) else None
    out = []
    for manifest in (manifests if isinstance(manifests, list) else [])[:5000]:
        if not isinstance(manifest, Mapping):
            continue
        row, _why = _skill_record(manifest)
        if row is None or row["kind"] == "optional":
            continue
        if row["kind"] == "catalog":
            source, how = hub_taps.get(taps.BUILTIN_CATALOG) or {}, "update"
        elif row["tap"] == taps.BUILTIN_PIN:
            source, how = hub_taps.get(taps.BUILTIN_PIN) or {}, "reinstall"
        else:
            source, how = hub_taps.get(row["tap"]) or {}, "reinstall"
        now = source.get("commit")
        if source.get("status") != "active" or not isinstance(now, str) or not _SHA40.fullmatch(now):
            continue
        if now != row["commit"]:
            out.append({"skill": row["slug"], "kind": row["kind"],
                        "source": hermes_catalog.REQUEST_SOURCE if row["kind"] == "catalog" else row["tap"],
                        "installed_commit": row["commit"], "source_commit": now, "how": how,
                        "identifier": row.get("identifier")})
    return sorted(out, key=lambda r: (r["source"], r["skill"]))


def _check(ns: argparse.Namespace, ctx) -> int:
    from .client import HubError
    from .nerva import EXIT_FAILED, EXIT_OK, EXIT_USAGE

    client = ctx.client()
    stale = stale_skills(client.get(IMPORTED), client.get(TAPS))
    if ns.action == "check":
        if ns.json:
            _dump(ctx, {"stale": stale})
            return EXIT_OK
        if not stale:
            ctx.say("every installed pinned skill is at its source's current commit")
            return EXIT_OK
        for row in stale:
            ctx.say(f"  {row['skill']:<28} {row['source']:<24} @{row['installed_commit'][:8]} -> "
                    f"@{row['source_commit'][:8]}")
        if any(r["how"] == "update" for r in stale):
            ctx.say("update catalog skills: nerva skills update [name ...]")
        if any(r["how"] == "reinstall" for r in stale):
            ctx.say("a tap or pin skill updates by removing it and installing it again at the new commit")
        return EXIT_OK
    catalog_rows = [r for r in stale if r["how"] == "update"]
    if ns.names:
        wanted = set()
        for name in ns.names:
            match = [r for r in catalog_rows if name in (r["skill"], r["identifier"])]
            if not match:
                ctx.err.write(f"{_plain(name, 80)}: not a catalog skill behind this hub's catalog "
                              "(see `nerva skills check`)\n")
                return EXIT_USAGE
            wanted.update(r["skill"] for r in match)
        catalog_rows = [r for r in catalog_rows if r["skill"] in wanted]
    results, failed = [], 0
    if not ns.force:
        # The hub's repair restores files the owner deleted without --force; an update must
        # not, so every edit (a deletion included) is checked here first, as `diff` sees it.
        from agents.core.skills.loader import _writable_skills_dir

        skills_dir, kept = _writable_skills_dir(), []
        for row in catalog_rows:
            local = diff_installed_skill(skills_dir, row["skill"])
            if not local.get("ok"):
                failed += 1
                results.append({"skill": row["skill"], "result": "refused",
                                "reason": "its folder cannot be checked for your edits from here "
                                          "(run this on the hub's machine, or pass --force)"})
            elif local["modified"]:
                failed += 1
                changed = sorted({f["status"] for f in local["files"]})
                results.append({"skill": row["skill"], "result": "refused",
                                "reason": f"you changed {len(local['files'])} file(s) ({', '.join(changed)}); "
                                          "see `nerva skills diff`, or pass --force to replace them "
                                          "(a copy of each edited file is kept)"})
            else:
                kept.append(row)
        catalog_rows = kept
    for row in catalog_rows:
        try:
            reply = client.post(CATALOG_INSTALL, {"skill": row["identifier"], "repair": True,
                                                  "force": bool(ns.force)})
            ok = isinstance(reply, Mapping) and reply.get("ok") is True
            results.append({"skill": row["skill"], "result": "updated" if ok else "failed"})
            failed += 0 if ok else 1
        except HubError as exc:
            failed += 1
            results.append({"skill": row["skill"], "result": "failed", "reason": _plain(exc.reason, 200)})
    if ns.json:
        _dump(ctx, {"results": results, "failed": failed})
    elif not results:
        ctx.say("no catalog skill is behind this hub's catalog")
    else:
        for item in results:
            reason = f" — {item['reason']}" if item.get("reason") else ""
            ctx.say(f"  {item['skill']}: {item['result']}{reason}")
        if failed:
            ctx.say("a skill you edited (or deleted files of) is not updated; see `nerva skills diff <name>`, "
                    "then `nerva skills update <name> --force` or `nerva skills reset <name>`")
    return EXIT_FAILED if failed else EXIT_OK


def installed_stock_folders(skills_dir: Path) -> list[str]:
    """Folder names under ``skills_dir`` whose sidecar says a catalog or optional install wrote them."""
    names = []
    try:
        with os.scandir(skills_dir) as iterator:
            entries = sorted(itertools.islice(iterator, MAX_INSTALLED_FOLDERS), key=lambda e: e.name)
    except OSError:
        return names
    for entry in entries:
        try:
            if not entry.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        data = _sidecar(Path(entry.path))
        if data and data.get("imported") is True and (
                (data.get("source") == "hermes" and data.get("source_catalog") == "vendored")
                or data.get("source") == OPTIONAL_SOURCE):
            names.append(entry.name)
    return names


def _list_modified(ns: argparse.Namespace, ctx) -> int:
    from agents.core.skills.loader import _writable_skills_dir

    from .nerva import EXIT_OK

    skills_dir = _writable_skills_dir()
    rows, unreadable, behind = [], [], []
    for name in installed_stock_folders(skills_dir):
        result = diff_installed_skill(skills_dir, name)
        if not result.get("ok"):
            unreadable.append({"skill": name, "reason": result.get("reason")})
            continue
        if result["modified"]:
            counts: dict[str, int] = {}
            for item in result["files"]:
                counts[item["status"]] = counts.get(item["status"], 0) + 1
            rows.append({"skill": result["skill"], "source": result["source"], "files": counts,
                         "behind": result["behind"]})
        elif result["behind"]:
            behind.append({"skill": result["skill"], "source": result["source"]})
    if ns.json:
        _dump(ctx, {"modified": rows, "behind_only": behind, "not_compared": unreadable})
        return EXIT_OK
    if not rows:
        ctx.say("no stock skill was edited")
    for row in rows:
        detail = ", ".join(f"{n} {k}" for k, n in sorted(row["files"].items()))
        note = "  (stock has also moved on)" if row["behind"] else ""
        ctx.say(f"  {_plain(row['skill'], 64):<28} {row['source']:<15} {detail}{note}")
    for row in behind:
        ctx.say(f"  {_plain(row['skill'], 64):<28} {row['source']:<15} not edited; stock has moved on "
                "since the install")
    for row in unreadable:
        ctx.say(f"  {_plain(row['skill'], 64):<28} not compared: {_plain(row['reason'], 120)}")
    if rows:
        ctx.say("see the changes: nerva skills diff <name>")
    return EXIT_OK


def _reset(ns: argparse.Namespace, ctx) -> int:
    from .nerva import EXIT_FAILED, _skill_catalog

    if not ns.yes:
        ctx.err.write(f"reset replaces every file you edited in {_plain(ns.skill, 80)} and restores the ones "
                      "you deleted (a copy of each edited file is kept on the hub)\n")
        if not _ask(ctx, "Reset it? [y/N] ", "not a terminal: re-run with --yes to reset"):
            return EXIT_FAILED
    return _skill_catalog(argparse.Namespace(catalog_action="repair", skill=ns.skill, force=True,
                                             json=ns.json), ctx)


def _pick(rows: list[Mapping], slug: str, source: str) -> tuple[Mapping | None, str]:
    """The one search row for ``slug`` (from ``source`` when given), or ``(None, why)``."""
    found = [row for row in rows if row.get("slug") == slug and (not source or row.get("tap") == source)]
    if not found:
        return None, "no source lists that skill (see `nerva skills search`)"
    if len(found) > 1:
        names = ", ".join(sorted({_plain(row.get("tap"), 40) for row in found}))
        return None, f"several sources list it ({names}); choose one with --from"
    return found[0], ""


def _install_or_inspect(ns: argparse.Namespace, ctx) -> int:
    from .nerva import EXIT_FAILED, EXIT_OK, EXIT_USAGE

    slug = ns.skill.strip()
    if not _SLUG.fullmatch(slug):
        ctx.err.write("give the skill's slug (lowercase letters, digits, . _ -)\n")
        return EXIT_USAGE
    source = ns.source.strip()
    if source and source not in ("hermes-catalog", "hermes"):
        source = _tap_ident(source) or ""
        if not source:
            ctx.err.write("--from takes a tap id (owner--repo), owner/repo, hermes-catalog or hermes\n")
            return EXIT_USAGE
    query = {"q": slug, "limit": SEARCH_MAX}
    if source:
        query["tap"] = source
    client = ctx.client()
    reply = client.get(f"{TAP_SEARCH}?{urlencode(query)}")
    rows = reply.get("results") if isinstance(reply, Mapping) else None
    if not isinstance(rows, list):
        ctx.err.write("unexpected reply from the hub: no results list\n")
        return EXIT_FAILED
    row, why = _pick([r for r in rows[:SEARCH_MAX] if isinstance(r, Mapping)], slug, source)
    if row is None:
        ctx.err.write(f"{slug}: {why}\n")
        return EXIT_FAILED
    tap = str(row.get("tap") or "")
    if ns.action == "inspect":
        if ns.json:
            _dump(ctx, row)
            return EXIT_OK
        ctx.say(f"{slug} from {_plain(tap, 60)} ({_plain(row.get('trust'), 10)}) "
                f"@{_plain(str(row.get('commit') or '')[:8], 8)}")
        ctx.say(f"  {_plain(row.get('description'), 300)}")
        ctx.say(f"  installable: {'yes' if row.get('installable') else 'no'}"
                + (f" — {_plain(row.get('reason'), 160)}" if row.get("reason") else ""))
        for key, label in (("required_env", "needs"), ("injection_flags", "flagged")):
            values = row.get(key) if isinstance(row.get(key), list) else []
            if values:
                ctx.say(f"  {label}: " + ", ".join(_plain(v, 60) for v in values[:32]))
        if row.get("carries_code"):
            ctx.say("  carries code: it would be installed quarantined, never run until you approve it")
        return EXIT_OK
    if not row.get("installable"):
        ctx.err.write(f"{slug}: not installable from {_plain(tap, 60)}: {_plain(row.get('reason'), 160)}\n")
        return EXIT_FAILED
    if tap == "hermes-catalog":
        from .nerva import _skill_catalog

        return _skill_catalog(argparse.Namespace(catalog_action="install", skill=slug, force=False,
                                                 json=ns.json), ctx)
    if not (tap == "hermes" or _TAP_ID.fullmatch(tap)):
        ctx.err.write("unexpected reply from the hub: the source is not a tap\n")
        return EXIT_FAILED
    reply = client.post(TAP_INSTALL, {"tap": tap, "skill": slug})
    if not isinstance(reply, Mapping) or reply.get("ok") is not True:
        ctx.err.write("unexpected reply from the hub: the install was not confirmed\n")
        return EXIT_FAILED
    if ns.json:
        _dump(ctx, reply)
        return EXIT_OK
    ctx.say(f"installed {slug} from {_plain(tap, 60)} (quarantined: its text is read as data, and any code "
            "never runs, until you vouch for it)")
    setup = reply.get("setup") if isinstance(reply.get("setup"), Mapping) else {}
    missing = setup.get("missing") if isinstance(setup.get("missing"), list) else []
    if missing:
        ctx.say("  still needs: " + ", ".join(_plain(v, 60) for v in missing[:32]))
    return EXIT_OK
