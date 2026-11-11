"""H025/H335 — skill taps: the owner's list of trusted skill sources.

Hermes keeps ``hermes skills tap add|list|remove`` (extra GitHub sources) and a hub that
searches across sources ranked by trust (``tools/skills_hub*.py``). Nerva's version, written
natively (see "Why not adopted" below):

**A tap is a trust root.** Adding one says "skills from this repository, at this exact
commit, may be offered to me". So:

* only an admin may ask (the routes are admin-guarded), and asking only queues an
  **approval card** at the approval queue's irreversible tier (:mod:`agents.core.autonomy.
  irreversible`): ``skills.tap_add`` with the repository URL, the commit and the trust level
  on the card. Nothing is fetched and nothing is searchable until a *person* accepts that
  card; a machine decision, an edit of the card, or a card whose payload no longer matches
  the recorded request is refused (:func:`apply_approved`);
* the ref is an exact 40-hex commit. A branch or tag can move under the owner; a commit
  cannot. Moving a tap to another commit is remove + add (a new card);
* removing a tap narrows trust, so it is immediate (no card).

**What a tap's content is: untrusted data.** :func:`refresh` reads the repository's tree at
the pinned commit and each ``<path>/<skill>/SKILL.md`` (and its ``references/``) through the
caller's fetcher, which crosses the action kernel's ``plugin.egress`` for every request.
Every entry is validated before it is kept (safe slug and paths, the SKILL.md's ``name``
equals its folder, the document passes ``validate_skill_md``, size caps); an entry that fails
is kept only as a refusal with its reason and is never installable. Descriptions are cut to
one line of 300 characters. Injection-like text is flagged on the row.

**Installing never takes a parallel path.** A tap only *produces the pin* (repository,
commit, entry path, sha256 of the SKILL.md and of each reference) that the existing remote
import consumes: ``POST /skills/import``'s own code (``routers/skills._import_remote``)
re-fetches each file at that commit, checks its digest, crosses ``skill.install`` twice and
lands the skill quarantined with ``PENDING_REVIEW``.

**Built-in taps.** Two official sources are always listed and cannot be removed:
``hermes-catalog`` (the vendored catalog, offline, :mod:`.hermes_catalog`) and ``hermes``
(the built-in import pin, ``hermes_pin_v2.json``). They sit at different upstream commits on
purpose; :func:`pin_alignment` measures the difference and the HUD shows it.

**Why not adopted.** Hermes's ``tools/skills_hub_sources.py`` (the well-known, URL, LobeHub
and browse.sh adapters) fetches mutable URLs with no commit pin, follows redirects, keeps a
disk memo cache through ``skills_hub_models.hub()`` and imports ``utils``; none of that maps
onto the exact-pin import, and wrapping it would need edits to the vendored text, which the
Adopt lane forbids (docs/hermes/ADOPT_LANE.md, "What may be adopted").
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import time
import unicodedata
from collections.abc import Awaitable, Callable
from pathlib import Path, PurePosixPath
from typing import Any

logger = logging.getLogger("jarvis.skills.taps")

#: The irreversible-tier kind an add request queues.
APPROVAL_KIND = "skills.tap_add"
TRUST_LEVELS = ("official", "trusted", "community")
#: What the owner may give a tap (``official`` is the built-in sources' alone).
OWNER_TRUST = ("trusted", "community")
TRUST_RANK = {name: rank for rank, name in enumerate(TRUST_LEVELS)}
BUILTIN_CATALOG = "hermes-catalog"
BUILTIN_PIN = "hermes"
MAX_TAPS = 32
MAX_TAP_SKILLS = 100
MAX_REFERENCES = 16
MAX_FILE_BYTES = 256 * 1024
MAX_TREE_BYTES = 4 * 1024 * 1024
MAX_REFRESH_BYTES = 8 * 1024 * 1024
SEARCH_LIMIT = 100
DESCRIPTION_CHARS = 300

_REPO_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PATH_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SLUG = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
_TAP_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,99}--[a-z0-9][a-z0-9._-]{0,99}\Z")
_LOCK = threading.RLock()

Fetch = Callable[[str, int], Awaitable[bytes]]


class TapRefused(ValueError):
    """A bounded refusal: a code the HUD shows, never upstream text."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(code)


# ── validation ──────────────────────────────────────────────────────────────────

def valid_repo(repo: object) -> bool:
    if not isinstance(repo, str) or len(repo) > 201:
        return False
    parts = repo.split("/")
    return len(parts) == 2 and all(_REPO_PART.fullmatch(p) for p in parts) and ".." not in repo


def valid_path(path: object, *, max_parts: int = 4) -> bool:
    if not isinstance(path, str) or not 1 <= len(path) <= 256 or "\\" in path:
        return False
    pure = PurePosixPath(path)
    return (pure.as_posix() == path and not pure.is_absolute() and 1 <= len(pure.parts) <= max_parts
            and all(_PATH_PART.fullmatch(p) and p not in (".", "..") for p in pure.parts))


def tap_id(repo: str) -> str:
    return repo.lower().replace("/", "--")


def _one_line(value: object, limit: int = DESCRIPTION_CHARS) -> str:
    text = "".join(ch if unicodedata.category(ch)[0] != "C" else " " for ch in str(value or ""))
    return " ".join(text.split())[:limit]


# ── the store (``<data>/skills/taps.json``) ─────────────────────────────────────

def _store_path() -> Path:
    from agents.core.paths import data_path

    return Path(data_path("skills", "taps.json"))


def _empty() -> dict:
    return {"format": "nerva-skill-taps/1", "taps": []}


def _read() -> dict:
    path = _store_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _empty()
    except OSError as exc:
        raise TapRefused("store_unavailable") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TapRefused("store_unavailable") from exc
    if not isinstance(data, dict) or not isinstance(data.get("taps"), list):
        raise TapRefused("store_unavailable")
    # A hand-edited row that does not hold up is dropped, never trusted.
    data["taps"] = [t for t in data["taps"] if _row_ok(t)][:MAX_TAPS]
    return data


def _row_ok(row: object) -> bool:
    return (isinstance(row, dict) and row.get("status") in ("pending", "active")
            and valid_repo(row.get("repo")) and row.get("id") == tap_id(row["repo"])
            and isinstance(row.get("commit"), str) and bool(_SHA40.fullmatch(row["commit"]))
            and valid_path(row.get("path")) and row.get("trust") in OWNER_TRUST)


def _write(data: dict) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".taps-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _find(data: dict, ident: str) -> dict | None:
    return next((t for t in data["taps"] if t["id"] == ident), None)


# ── the built-in sources ────────────────────────────────────────────────────────

def _import_pin():
    from .importer import _load_hermes_pin

    return _load_hermes_pin()


def builtin_taps() -> list[dict]:
    from . import hermes_catalog

    rows = []
    try:
        catalog = hermes_catalog.load()
        rows.append({"id": BUILTIN_CATALOG, "builtin": True, "kind": "vendored", "trust": "official",
                     "status": "active", "repo": catalog.index.get("repository"), "commit": catalog.commit,
                     "release_tag": None, "skills": len(catalog.index.get("skills", [])),
                     "install": "catalog",
                     "note": "vendored with this hub (Adopt lane); installs offline, byte-checked"})
    except Exception as exc:  # noqa: BLE001 — a broken catalog is listed as such
        rows.append({"id": BUILTIN_CATALOG, "builtin": True, "kind": "vendored", "trust": "official",
                     "status": "unavailable", "error": type(exc).__name__})
    try:
        pin = _import_pin()
        rows.append({"id": BUILTIN_PIN, "builtin": True, "kind": "pin", "trust": "official",
                     "status": "active", "repo": pin.repository, "commit": pin.commit,
                     "release_tag": pin.release_tag, "skills": len(pin.skills), "install": "import",
                     "note": "the built-in import pin; fetched at install, digest-checked"})
    except Exception as exc:  # noqa: BLE001
        rows.append({"id": BUILTIN_PIN, "builtin": True, "kind": "pin", "trust": "official",
                     "status": "unavailable", "error": type(exc).__name__})
    return rows


_ALIGNMENT: dict[str, Any] = {}


def pin_alignment() -> dict:
    """How the two official pins differ, measured on their own records (cached per pair).

    The built-in import pin must name a *release* (``hermes_pin_v2.json``'s loader refuses
    any other tag, and each skill's page in docs/skills/hermes/ cites it), while the vendored
    catalog follows the Adopt lane's commit on ``main``. For each skill the import pin
    lists: does the catalog hold the same SKILL.md bytes, different bytes, or no such skill?"""
    from . import hermes_catalog

    try:
        pin = _import_pin()
        catalog = hermes_catalog.load()
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": type(exc).__name__}
    key = f"{pin.commit}:{catalog.commit}"
    if key in _ALIGNMENT:
        return _ALIGNMENT[key]
    by_path = {}
    for item in catalog.index.get("skills", []):
        for f in item.get("files") or []:
            if f.get("path") == "SKILL.md":
                by_path[str(item.get("path"))] = f.get("sha256")
    same = changed = absent = 0
    for entry in pin.skills:
        digest = by_path.get(entry.path.rsplit("/", 1)[0])
        if digest is None:
            absent += 1
        elif digest == entry.content_sha256:
            same += 1
        else:
            changed += 1
    result = {
        "available": True, "aligned": pin.commit == catalog.commit,
        "import_pin": {"release_tag": pin.release_tag, "commit": pin.commit, "skills": len(pin.skills)},
        "catalog_pin": {"commit": catalog.commit, "skills": len(catalog.index.get("skills", []))},
        "same_bytes": same, "changed": changed, "not_in_catalog": absent,
        "why": ("The import pin names a Hermes release (v-tag) and must; the vendored catalog is the "
                "Adopt lane's main-branch commit. Each source installs at its own pin, shown on every row."),
    }
    _ALIGNMENT.clear()
    _ALIGNMENT[key] = result
    return result


# ── listing ─────────────────────────────────────────────────────────────────────

def _public(row: dict) -> dict:
    out = {k: row.get(k) for k in ("id", "repo", "commit", "path", "trust", "status", "task_id",
                                   "requested_at", "approved_by", "approved_at", "refreshed_at",
                                   "index_error", "truncated")}
    index = row.get("index") or []
    out.update({"builtin": False, "kind": "github", "install": "import",
                "source_url": source_url(row["repo"], row["commit"], row["path"]),
                "skills": sum(1 for e in index if not e.get("refused")),
                "refused": sum(1 for e in index if e.get("refused"))})
    return out


def source_url(repo: str, commit: str, path: str) -> str:
    return f"https://github.com/{repo}/tree/{commit}/{path}"


def listing() -> dict:
    with _LOCK:
        data = _read()
    return {"taps": builtin_taps() + [_public(t) for t in data["taps"]],
            "pin_alignment": pin_alignment(), "trust_levels": list(TRUST_LEVELS)}


# ── add (an approval card), apply, remove ───────────────────────────────────────

def _payload(row: dict) -> dict:
    return {"operation": APPROVAL_KIND, "tap_id": row["id"], "repo": row["repo"],
            "commit": row["commit"], "path": row["path"], "trust": row["trust"],
            "source_url": source_url(row["repo"], row["commit"], row["path"])}


def request_add(orch: Any, *, repo: str, commit: str, path: str = "skills", trust: str = "community",
                requested_by: str = "owner") -> dict:
    """Queue the card. ``{"pending": task_id, "tap": …}`` or raise :class:`TapRefused`."""
    from agents.core.autonomy import irreversible

    if not valid_repo(repo):
        raise TapRefused("invalid_repo")
    if not isinstance(commit, str) or not _SHA40.fullmatch(commit):
        raise TapRefused("commit_not_pinned", "a tap needs an exact 40-hex commit; branches and tags move")
    if not valid_path(path):
        raise TapRefused("invalid_path")
    if trust not in OWNER_TRUST:
        raise TapRefused("invalid_trust")
    ident = tap_id(repo)
    if ident in (BUILTIN_CATALOG, BUILTIN_PIN):
        raise TapRefused("reserved")
    with _LOCK:
        data = _read()
        if _find(data, ident) is not None:
            raise TapRefused("exists")
        if len(data["taps"]) >= MAX_TAPS:
            raise TapRefused("too_many_taps")
        row = {"id": ident, "repo": repo, "commit": commit, "path": path, "trust": trust,
               "status": "pending", "requested_by": requested_by, "requested_at": time.time()}
        payload = _payload(row)
        preview = {"action": "Trust a new skill source (tap)", "source_url": payload["source_url"],
                   "repository": repo, "commit": commit, "path": path, "trust": trust,
                   "effect": ("skills in this repository at this exact commit become searchable and "
                              "installable; each install still crosses skill.install and lands "
                              "quarantined for your review")}
        queued = irreversible.enqueue(orch, APPROVAL_KIND,
                                      title=f"Trust skill source {repo}@{commit[:8]} ({trust})",
                                      payload=payload, preview=preview)
        if "pending" not in queued:
            raise TapRefused(str(queued.get("refused") or "approval_queue_unavailable"))
        row["task_id"] = queued["pending"]
        row["payload_sha256"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        data["taps"].append(row)
        _write(data)
    return {"pending": row["task_id"], "tap": _public(row)}


async def apply_approved(task: Any, orch: Any) -> dict:
    """A person accepted the card (``irreversible.execute`` checked who decided): activate
    the tap the card names, only as it was asked."""
    decision = str(getattr(task, "decision", "") or "").strip().lower()
    if decision not in ("accept", "approve"):
        return {"status": "refused", "reason": "edit_not_supported"}
    payload = dict(getattr(task, "payload", {}) or {})
    task_id = getattr(task, "id", None)
    with _LOCK:
        data = _read()
        row = _find(data, str(payload.get("tap_id") or ""))
        if row is None or row.get("task_id") != task_id:
            return {"status": "refused", "reason": "not_requested"}
        if row["status"] != "pending":
            return {"status": "refused", "reason": "already_applied"}
        expected = _payload(row)
        if any(payload.get(k) != v for k, v in expected.items()):
            return {"status": "refused", "reason": "payload_changed"}
        row["status"] = "active"
        row["approved_by"] = str(getattr(task, "decided_by", "") or "owner")
        row["approved_at"] = time.time()
        _write(data)
    _audit(orch, row["approved_by"], "skill.tap.add",
           f"skill source {row['repo']}@{row['commit'][:8]} trusted as {row['trust']} (task {task_id})",
           {"tap": row["id"], "commit": row["commit"], "trust": row["trust"]})
    return {"status": "ok", "tap": row["id"]}


def remove(orch: Any, ident: str, *, actor: str = "owner") -> dict:
    if ident in (BUILTIN_CATALOG, BUILTIN_PIN):
        raise TapRefused("builtin")
    with _LOCK:
        data = _read()
        row = _find(data, ident)
        if row is None:
            raise TapRefused("not_found")
        data["taps"] = [t for t in data["taps"] if t["id"] != ident]
        _write(data)
    _audit(orch, actor, "skill.tap.remove", f"skill source {row['repo']} removed", {"tap": ident})
    return {"removed": ident}


def _audit(orch: Any, actor: str, action: str, why: str, metadata: dict) -> None:
    audit = getattr(orch, "intent_log", None)
    if callable(getattr(audit, "record", None)):
        try:
            audit.record(actor=actor, action=action, why=why, cause="skills.taps", metadata=metadata)
        except Exception:  # noqa: BLE001 — a projection
            logger.warning("skill tap intent projection failed", exc_info=True)


# ── refresh (the tap's index, read at its commit) ───────────────────────────────

def _tree_url(row: dict) -> str:
    return f"https://api.github.com/repos/{row['repo']}/git/trees/{row['commit']}?recursive=1"


def _raw_url(row: dict, path: str) -> str:
    return f"https://raw.githubusercontent.com/{row['repo']}/{row['commit']}/{path}"


def _candidates(tree: object, prefix: str) -> tuple[dict[str, dict], bool]:
    """``{slug: {"entry": path, "refs": [paths], "code": bool}}`` from a tree listing."""
    if not isinstance(tree, dict) or not isinstance(tree.get("tree"), list):
        raise TapRefused("bad_index")
    found: dict[str, dict] = {}
    base = prefix.rstrip("/") + "/"
    for item in tree["tree"][:50_000]:
        if not isinstance(item, dict) or item.get("type") != "blob":
            continue
        path = item.get("path")
        if not isinstance(path, str) or not path.startswith(base):
            continue
        rest = path[len(base):].split("/")
        if len(rest) < 2:
            continue
        slug = rest[0]
        row = found.setdefault(slug, {"entry": None, "refs": [], "code": False, "unsafe": False})
        if not valid_path(path, max_parts=10):
            row["unsafe"] = True
            continue
        if rest[1:] == ["SKILL.md"]:
            row["entry"] = path
        elif rest[1] == "references" and len(rest) >= 3:
            row["refs"].append(path)
        else:
            from .hermes_catalog import is_executable_file

            if is_executable_file("/".join(rest[1:])):
                row["code"] = True
    return found, bool(tree.get("truncated"))


async def _fetch_checked(fetch: Fetch, url: str, limit: int, budget: list[int]) -> bytes:
    if budget[0] <= 0:
        raise TapRefused("refresh_budget")
    raw = await fetch(url, min(limit, budget[0]))
    if not isinstance(raw, (bytes, bytearray)) or len(raw) > min(limit, budget[0]):
        raise TapRefused("fetch_failed")
    budget[0] -= len(raw)
    return bytes(raw)


async def _entry(fetch: Fetch, row: dict, slug: str, cand: dict, budget: list[int]) -> dict:
    """One validated index entry, or a refusal row (never installable)."""
    from .hermes_catalog import _entry_metadata, _frontmatter
    from .validate import validate_skill_md

    def refused(reason: str) -> dict:
        return {"slug": slug[:64], "refused": reason}

    if not _SLUG.fullmatch(slug):
        return refused("unsafe_name")
    if cand.get("unsafe"):
        return refused("unsafe_path")
    if not cand.get("entry"):
        return refused("no_skill_md")
    if len(cand["refs"]) > MAX_REFERENCES:
        return refused("too_many_references")
    raw = await _fetch_checked(fetch, _raw_url(row, cand["entry"]), MAX_FILE_BYTES, budget)
    try:
        text = raw.decode("utf-8")
        fm = _frontmatter(text)
    except (UnicodeDecodeError, ValueError):
        return refused("invalid_skill_md")
    if validate_skill_md(raw):
        return refused("invalid_skill_md")
    if fm.get("name") != slug:
        return refused("name_mismatch")
    meta = _entry_metadata(text, fm)
    refs = []
    for ref in sorted(cand["refs"]):
        content = await _fetch_checked(fetch, _raw_url(row, ref), MAX_FILE_BYTES, budget)
        refs.append({"path": ref, "content_sha256": hashlib.sha256(content).hexdigest()})
    return {"slug": slug, "entry_path": cand["entry"], "content_sha256": hashlib.sha256(raw).hexdigest(),
            "references": refs, "description": _one_line(meta["description"]),
            "required_env": [n for n in meta["required_env"] if isinstance(n, str)][:32],
            "injection_flags": list(meta["injection_flags"])[:8], "carries_code": bool(cand["code"])}


async def refresh(orch: Any, ident: str, fetch: Fetch) -> dict:
    """Read an active tap's index at its pinned commit through *fetch* (which crosses the
    kernel's egress gate per request). Replaces the stored index only when it all worked."""
    with _LOCK:
        data = _read()
        row = _find(data, ident)
    if row is None:
        raise TapRefused("not_found")
    if row["status"] != "active":
        raise TapRefused("not_approved")
    budget = [MAX_REFRESH_BYTES]
    raw_tree = await _fetch_checked(fetch, _tree_url(row), MAX_TREE_BYTES, budget)
    try:
        tree = json.loads(raw_tree)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TapRefused("bad_index") from exc
    candidates, truncated = _candidates(tree, row["path"])
    index = []
    for slug in sorted(candidates)[:MAX_TAP_SKILLS]:
        index.append(await _entry(fetch, row, slug, candidates[slug], budget))
    with _LOCK:
        data = _read()
        current = _find(data, ident)
        if current is None or current["commit"] != row["commit"] or current["status"] != "active":
            raise TapRefused("changed_during_refresh")
        current["index"] = index
        current["refreshed_at"] = time.time()
        current["truncated"] = truncated or len(candidates) > MAX_TAP_SKILLS
        current.pop("index_error", None)
        _write(data)
    _audit(orch, "owner", "skill.tap.refresh", f"skill source {row['repo']} index read", {
        "tap": ident, "skills": sum(1 for e in index if not e.get("refused")),
        "refused": sum(1 for e in index if e.get("refused"))})
    return _public(current)


# ── search and install pins ─────────────────────────────────────────────────────

def _valid_entry(entry: object) -> bool:
    """A stored index entry still holds up (the store is re-read, never trusted)."""
    if not isinstance(entry, dict) or entry.get("refused") or not _SLUG.fullmatch(str(entry.get("slug"))):
        return False
    refs = entry.get("references")
    return (valid_path(entry.get("entry_path"), max_parts=10)
            and str(entry.get("entry_path")).endswith(f"/{entry['slug']}/SKILL.md")
            and isinstance(entry.get("content_sha256"), str) and bool(_SHA256.fullmatch(entry["content_sha256"]))
            and isinstance(refs, list) and len(refs) <= MAX_REFERENCES
            and all(isinstance(r, dict) and valid_path(r.get("path"), max_parts=10)
                    and isinstance(r.get("content_sha256"), str) and bool(_SHA256.fullmatch(r["content_sha256"]))
                    for r in refs))


def install_pin(ident: str, slug: str) -> tuple[dict, dict]:
    """``(tap row, pin dict)`` for ``POST /skills/import``; :class:`TapRefused` otherwise."""
    with _LOCK:
        data = _read()
        row = _find(data, ident)
    if row is None:
        raise TapRefused("not_found")
    if row["status"] != "active":
        raise TapRefused("not_approved")
    entry = next((e for e in row.get("index") or [] if isinstance(e, dict) and e.get("slug") == slug), None)
    if entry is None:
        raise TapRefused("skill_not_in_tap")
    if entry.get("refused"):
        raise TapRefused("refused_entry", str(entry["refused"]))
    if not _valid_entry(entry):
        raise TapRefused("refused_entry", "invalid_index_entry")
    pin = {"repo": row["repo"], "commit": row["commit"], "entry_path": entry["entry_path"],
           "content_sha256": entry["content_sha256"],
           "references": [{"path": r["path"], "content_sha256": r["content_sha256"]} for r in entry["references"]]}
    return row, pin


def _score(needle: str, slug: str, description: str, extra: list) -> int | None:
    if not needle:
        return 3
    if slug == needle:
        return 0
    if slug.startswith(needle):
        return 1
    if needle in slug:
        return 2
    if any(needle in str(v or "").casefold() for v in [description, *extra]):
        return 3
    return None


def search(query: str = "", *, tap: str = "", limit: int = 40, imported: list | None = None) -> dict:
    """One result list across every active source, ranked official > trusted > community,
    then by how well the slug matches. Each row says how it installs."""
    from . import hermes_catalog

    needle = str(query or "").strip().casefold()[:100]
    limit = max(1, min(int(limit or 40), SEARCH_LIMIT))
    results = []
    if tap in ("", BUILTIN_CATALOG):
        listing_ = hermes_catalog.listing(imported or [])
        for r in listing_.get("skills", []):
            score = _score(needle, str(r.get("slug") or ""), str(r.get("description") or ""),
                           [r.get("category"), *(r.get("tags") or [])])
            if score is not None:
                results.append({"tap": BUILTIN_CATALOG, "trust": "official", "slug": r.get("slug"),
                                "description": r.get("description") or "", "commit": listing_.get("commit"),
                                "installable": bool(r.get("installable")), "install": "catalog",
                                "reason": r.get("reason") or ("carries code" if r.get("kind") == "upstream_only"
                                                              else ""),
                                "required_env": r.get("required_env") or [],
                                "injection_flags": r.get("injection_flags") or [], "_score": score})
    if tap in ("", BUILTIN_PIN):
        try:
            pin = _import_pin()
        except Exception:  # noqa: BLE001
            pin = None
        for entry in pin.skills if pin else ():
            score = _score(needle, entry.slug, "", [entry.tier])
            if score is not None:
                results.append({"tap": BUILTIN_PIN, "trust": "official", "slug": entry.slug,
                                "description": f"{entry.tier} · {pin.release_tag}", "commit": pin.commit,
                                "installable": True, "install": "import", "reason": "",
                                "required_env": [], "injection_flags": [], "_score": score})
    with _LOCK:
        data = _read()
    for row in data["taps"]:
        if row["status"] != "active" or (tap and tap != row["id"]):
            continue
        for entry in row.get("index") or []:
            if not isinstance(entry, dict):
                continue
            slug = str(entry.get("slug") or "")
            score = _score(needle, slug, str(entry.get("description") or ""), [])
            if score is None:
                continue
            ok = _valid_entry(entry)
            results.append({"tap": row["id"], "trust": row["trust"], "slug": slug,
                            "description": _one_line(entry.get("description")), "commit": row["commit"],
                            "installable": ok, "install": "import",
                            "reason": str(entry.get("refused") or ("" if ok else "invalid_index_entry")),
                            "required_env": list(entry.get("required_env") or [])[:32],
                            "injection_flags": list(entry.get("injection_flags") or [])[:8],
                            "carries_code": bool(entry.get("carries_code")), "_score": score})
    results.sort(key=lambda r: (TRUST_RANK.get(r["trust"], 9), not r["installable"], r["_score"], r["slug"]))
    for r in results:
        r.pop("_score", None)
    return {"query": needle, "matched": len(results), "results": results[:limit]}


__all__ = ["APPROVAL_KIND", "BUILTIN_CATALOG", "BUILTIN_PIN", "OWNER_TRUST", "TRUST_LEVELS", "TapRefused",
           "apply_approved", "builtin_taps", "install_pin", "listing", "pin_alignment", "refresh", "remove",
           "request_add", "search"]
