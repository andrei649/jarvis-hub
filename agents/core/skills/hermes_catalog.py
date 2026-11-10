"""hermes_catalog.py — Hermes's skill catalog, browsable and installable (Adopt lane, slice 3).

Hermes Agent (MIT, NousResearch/hermes-agent) ships its skills as folders with a
``SKILL.md`` under ``skills/`` and ``optional-skills/``. The Adopt lane vendors the
**instruction-only** ones byte-identical under ``agents/vendor/hermes/<upstream path>``
(``scripts/hermes_vendor.py catalog``), with a sha256 per file in ``MANIFEST.json`` and an
index of every upstream skill in ``SKILLS_CATALOG.json``. Guide: ``docs/hermes/ADOPT_LANE.md``.

Nothing here is a second skills system:

* **Inert until installed.** ``agents/vendor/hermes`` is not a skill root
  (``loader.skill_roots``), so a vendored skill is never discovered, listed to a model or put
  in a prompt. It is data until the owner installs it.
* **Installed through the import path.** :func:`install` checks the vendored bytes against
  the manifest and hands them to ``SkillImporter._save_skill`` — the same call the pinned
  Hermes import (``import_from_hermes``) makes — so the SKILL.md validator, the folder check
  (``exists``), the name-holder check (``name_taken``), the install id and the provenance
  sidecar are the ones every import gets. The sidecar's ``source`` is ``hermes``, as for the
  pinned import, and its provenance says the catalog commit.
* **No more trust than an import.** An installed catalog skill is an external, unsigned
  skill: the prompt catalog and index drop a row whose text is injection-flagged,
  ``skill_view`` serves its text fenced as DATA until the owner vouches for it, and its
  ``required_env`` is declared to the code tool only for a vouched skill
  (``tools.declare_skill_environment``). The injection flags are shown in the listing before
  install, as the local migration's review card shows them.
* **Code is not carried.** A Hermes skill with a script (``.py``, ``.sh``, ``.mjs`` …) is
  listed as ``upstream_only`` with its file list, and the catalog refuses to install it:
  Nerva's import paths copy a SKILL.md and plain data only, and the one path that carries
  code (a signed marketplace package, ``marketplace.install_from_zip``) is the owner's to
  take. A skill with other non-data files (HTML, images, PDFs) is ``excluded``.

Frontmatter is never rewritten: the SKILL.md bytes are upstream's, so a Hermes key Nerva
does not map is still in the file (and in ``skill_view``). The index names those keys
(``unmapped_keys``) and the environment-variable names a skill's text mentions without
declaring them (``undeclared_env_mentions``), so the owner sees both before installing.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

VENDOR_ROOT = Path(__file__).resolve().parents[2] / "vendor" / "hermes"
INDEX_NAME = "SKILLS_CATALOG.json"
INDEX_FORMAT = "nerva-hermes-skills-catalog/1"
#: The upstream folders that hold skills.
CATALOG_ROOTS = ("skills", "optional-skills")
#: What ``POST /skills/import`` takes as ``source`` for a catalog install.
REQUEST_SOURCE = "hermes-catalog"
#: The importer's ``source`` for the installed folder: the same as the pinned Hermes import.
INSTALL_SOURCE = "hermes"
UPSTREAM_REPOSITORY = "NousResearch/hermes-agent"

KIND_INSTRUCTION = "instruction"
KIND_UPSTREAM_ONLY = "upstream_only"
KIND_EXCLUDED = "excluded"

#: Plain data a catalog skill may hold besides its SKILL.md (``hermes_vendor.CATALOG_SUFFIXES``).
DATA_SUFFIXES = frozenset({".md", ".txt", ".yaml", ".yml", ".json"})
DATA_NAMES = frozenset({"LICENSE"})
#: Files that make a skill one that carries code.
EXECUTABLE_SUFFIXES = frozenset({
    ".py", ".pyw", ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd", ".js", ".mjs", ".cjs",
    ".ts", ".tsx", ".jsx", ".rb", ".pl", ".php", ".lua", ".go", ".rs", ".java", ".jar", ".wasm",
    ".so", ".dylib", ".dll", ".exe", ".bin", ".applescript", ".scpt",
})
EXECUTABLE_NAMES = frozenset({"Makefile", "Dockerfile", "Justfile", "Rakefile"})
#: The largest supporting file a catalog skill may carry (the SKILL.md cap is the validator's).
MAX_FILE_BYTES = 256 * 1024
MAX_FILES = 64
#: Folder names reserved for the hub's own records in an installed skill folder.
RESERVED_TOP = frozenset({"SKILL.md", "manifest.json", "SKILL.sig", "PENDING_REVIEW",
                          "EXTERNAL_SOURCE", "OWNER_APPROVED_IN_PROCESS"})
_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ENV_MENTION = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_(?:API_KEY|TOKEN|SECRET|KEY|PASSWORD)\b")
_DESCRIPTION_CHARS = 300


class CatalogError(Exception):
    """The catalog cannot be read (missing, malformed, or not what the manifest records)."""


def is_data_file(rel: str) -> bool:
    """Whether a supporting file of a catalog skill is plain data by name."""
    name = PurePosixPath(rel).name
    return name in DATA_NAMES or PurePosixPath(rel).suffix.lower() in DATA_SUFFIXES


def is_executable_file(rel: str) -> bool:
    name = PurePosixPath(rel).name
    return name in EXECUTABLE_NAMES or PurePosixPath(rel).suffix.lower() in EXECUTABLE_SUFFIXES


def safe_extra_path(rel: str) -> bool:
    """Whether ``rel`` may be written as a supporting file of an installed skill: a plain
    relative path of safe parts, data by name, not a hub record at the folder's top."""
    if not isinstance(rel, str) or not rel or "\\" in rel or len(rel) > 512:
        return False
    pure = PurePosixPath(rel)
    if pure.is_absolute() or pure.as_posix() != rel or len(pure.parts) > 5:
        return False
    if any(part in ("", ".", "..") or not _PART.match(part) for part in pure.parts):
        return False
    if len(pure.parts) == 1 and pure.name in RESERVED_TOP:
        return False
    return is_data_file(rel)


# ── building the index (scripts/hermes_vendor.py catalog) ───────────────────────

def _frontmatter(text: str) -> dict:
    from .frontmatter import split_frontmatter

    data, _body = split_frontmatter(text, lenient=False)
    return data if isinstance(data, dict) else {}


def _unmapped_keys(fm: dict) -> list[str]:
    """Frontmatter keys Nerva's contract does not read (kept in the file all the same)."""
    from .frontmatter import _HERMES_LIST_KEYS
    from .validate import _KNOWN_KEYS

    out = sorted(str(k) for k in fm if str(k) not in _KNOWN_KEYS)
    meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
    out += sorted(f"metadata.{k}" for k in meta if k != "hermes")
    hermes = meta.get("hermes") if isinstance(meta.get("hermes"), dict) else {}
    mapped = {"tags", "category", "upstream_skill", "config", "related_skills", *_HERMES_LIST_KEYS}
    out += sorted(f"metadata.hermes.{k}" for k in hermes if k not in mapped)
    return out


def _entry_metadata(text: str, fm: dict) -> dict:
    from ..security import quarantine
    from . import frontmatter as _fm

    contract = _fm.contract_fields(fm)
    declared = [e["name"] for e in contract["required_environment_variables"]]
    mentioned = sorted(set(_ENV_MENTION.findall(text)) - set(declared))
    return {
        "description": _fm.cap_description(fm.get("description"))[:_DESCRIPTION_CHARS],
        "version": _fm.text(fm.get("version")),
        "license": _fm.joined(fm.get("license")),
        "tags": contract["tags"],
        "platforms": contract["platforms"],
        "required_env": declared,
        "required_credential_files": [c["path"] for c in contract["required_credential_files"]],
        "undeclared_env_mentions": mentioned,
        "unmapped_keys": _unmapped_keys(fm),
        "injection_flags": sorted(set(quarantine.detect_injection_normalized(text))),
    }


def _classify(files: dict[str, bytes], fm: dict, folder: str, text: str | None) -> tuple[str, str]:
    from .validate import validate_skill_md

    if any(is_executable_file(rel) for rel in files):
        return KIND_UPSTREAM_ONLY, "carries_code"
    if any(not is_data_file(rel) for rel in files if rel != "SKILL.md"):
        return KIND_EXCLUDED, "files_outside_data_allowlist"
    if len(files) > MAX_FILES or any(len(b) > MAX_FILE_BYTES for rel, b in files.items() if rel != "SKILL.md"):
        return KIND_EXCLUDED, "file_too_large"
    if text is None:
        return KIND_EXCLUDED, "not_utf8"
    if validate_skill_md(files["SKILL.md"]):
        return KIND_EXCLUDED, "invalid_skill_md"
    if fm.get("name") != folder:
        return KIND_EXCLUDED, "declared_name_differs_from_folder"
    if any(not safe_extra_path(rel) for rel in files if rel != "SKILL.md"):
        return KIND_EXCLUDED, "unsafe_file_path"
    return KIND_INSTRUCTION, ""


def build_index(upstream: Path, commit: str) -> dict:
    """The catalog of every skill folder in an upstream clone, classified. Read-only;
    refuses a linked folder or file (it is listed as excluded, never followed)."""
    upstream = Path(upstream)
    entries: list[dict] = []
    seen: dict[str, str] = {}
    for root in CATALOG_ROOTS:
        base = upstream / root
        if not base.is_dir() or base.is_symlink():
            continue
        for skill_md in sorted(base.rglob("SKILL.md")):
            folder = skill_md.parent
            rel_dir = folder.relative_to(upstream).as_posix()
            linked = any(p.is_symlink() for p in [folder, *folder.rglob("*")]) or any(
                parent.is_symlink() for parent in folder.relative_to(upstream).parents if str(parent) != ".")
            files: dict[str, bytes] = {}
            if not linked:
                for path in sorted(folder.rglob("*")):
                    if path.is_file():
                        files[path.relative_to(folder).as_posix()] = path.read_bytes()
            nested = [rel for rel in files if rel != "SKILL.md" and PurePosixPath(rel).name == "SKILL.md"]
            try:
                text = files.get("SKILL.md", b"").decode("utf-8")
            except UnicodeDecodeError:
                text = None
            fm = _frontmatter(text) if text else {}
            category = rel_dir.split("/")[1] if rel_dir.count("/") >= 2 else ""
            entry: dict[str, Any] = {
                "slug": folder.name, "name": str(fm.get("name") or ""), "path": rel_dir,
                "root": root, "category": category,
            }
            if linked:
                kind, reason = KIND_EXCLUDED, "symlink"
            elif nested:
                kind, reason = KIND_EXCLUDED, "nested_skill"
            else:
                kind, reason = _classify(files, fm, folder.name, text)
            if kind == KIND_INSTRUCTION and folder.name in seen:
                kind, reason = KIND_EXCLUDED, f"duplicate_slug_of:{seen[folder.name]}"
            if kind == KIND_INSTRUCTION:
                seen[folder.name] = rel_dir
            entry["kind"], entry["reason"] = kind, reason
            if text is not None:
                entry.update(_entry_metadata(text, fm))
            entry["files"] = [{"path": rel, "sha256": hashlib.sha256(data).hexdigest(),
                               "bytes": len(data), "executable": is_executable_file(rel)}
                              for rel, data in sorted(files.items())]
            entries.append(entry)
    entries.sort(key=lambda e: e["path"])
    counts = {kind: sum(1 for e in entries if e["kind"] == kind)
              for kind in (KIND_INSTRUCTION, KIND_UPSTREAM_ONLY, KIND_EXCLUDED)}
    return {"format": INDEX_FORMAT, "repository": UPSTREAM_REPOSITORY, "commit": commit,
            "counts": counts, "skills": entries}


def dump_index(index: dict) -> str:
    return json.dumps(index, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


# ── reading it (the routes) ──────────────────────────────────────────────────

@dataclass(frozen=True)
class Catalog:
    root: Path
    index: dict
    manifest: dict

    @property
    def commit(self) -> str:
        return str(self.index.get("commit") or "")

    def entry(self, slug: str) -> dict | None:
        for item in self.index.get("skills", []):
            if item.get("slug") == slug and item.get("kind") == KIND_INSTRUCTION:
                return item
        return next((item for item in self.index.get("skills", []) if item.get("slug") == slug), None)


def _read_json(path: Path) -> dict:
    try:
        if path.is_symlink() or not path.is_file():
            raise CatalogError(f"{path.name} is missing")
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"{path.name} cannot be read") from exc
    if not isinstance(data, dict):
        raise CatalogError(f"{path.name} is not an object")
    return data


@functools.lru_cache(maxsize=4)
def _load_cached(root: str, stamp: tuple) -> Catalog:
    base = Path(root)
    index = _read_json(base / INDEX_NAME)
    manifest = _read_json(base / "MANIFEST.json")
    if index.get("format") != INDEX_FORMAT or not isinstance(index.get("skills"), list):
        raise CatalogError("the catalog index has an unknown format")
    if index.get("commit") != (manifest.get("upstream") or {}).get("commit"):
        raise CatalogError("the catalog index and MANIFEST.json name different commits")
    return Catalog(base, index, manifest)


def load(root: Path | None = None) -> Catalog:
    base = Path(root or VENDOR_ROOT)
    stamps = []
    for name in (INDEX_NAME, "MANIFEST.json"):
        try:
            st = (base / name).stat()
            stamps.append((st.st_mtime_ns, st.st_size))
        except OSError:
            stamps.append(None)
    return _load_cached(str(base), tuple(stamps))


def _installed_hermes(imported: list) -> dict[str, str]:
    """``{folder name: commit}`` of the Hermes imports on disk (any pin)."""
    out: dict[str, str] = {}
    for row in imported or []:
        if isinstance(row, dict) and row.get("source") == INSTALL_SOURCE:
            path = str(row.get("source_path") or "")
            slug = PurePosixPath(path).parent.name if path.endswith("/SKILL.md") else str(row.get("name") or "")
            if slug:
                out[slug] = str(row.get("source_commit") or "")
    return out


def listing(imported: list | None = None, root: Path | None = None) -> dict:
    """What the HUD shows: the catalog's counts and one row a skill (no file bytes)."""
    try:
        catalog = load(root)
    except CatalogError as exc:
        return {"available": False, "error": str(exc), "skills": []}
    installed = _installed_hermes(imported or [])
    rows = []
    for item in catalog.index.get("skills", []):
        row = {key: item.get(key) for key in (
            "slug", "name", "path", "root", "category", "kind", "reason", "description", "tags",
            "platforms", "required_env", "required_credential_files", "undeclared_env_mentions",
            "unmapped_keys", "injection_flags")}
        files = item.get("files") or []
        row["files"] = len(files)
        if item.get("kind") == KIND_UPSTREAM_ONLY:
            # What code it carries, by name: the owner sees it before taking the code path.
            row["code_files"] = [f["path"] for f in files if f.get("executable")]
        row["installable"] = item.get("kind") == KIND_INSTRUCTION
        if item.get("kind") == KIND_INSTRUCTION and item.get("slug") in installed:
            row["installed_commit"] = installed[item["slug"]]
        rows.append(row)
    return {"available": True, "source": REQUEST_SOURCE, "repository": catalog.index.get("repository"),
            "commit": catalog.commit, "counts": catalog.index.get("counts", {}), "skills": rows}


# ── installing one (POST /skills/import with source "hermes-catalog") ────────

@dataclass(frozen=True)
class InstallRefusal:
    reason: str
    detail: str = ""
    files: tuple = ()


def verified_files(catalog: Catalog, entry: dict) -> dict[str, bytes]:
    """The vendored bytes of one instruction skill, each checked against the index and
    MANIFEST.json (upstream sha256 == vendored sha256 == index sha256). Raises
    :class:`CatalogError` on any difference, a missing file, a link or a stray path."""
    recorded = {f["path"]: f for f in catalog.manifest.get("files", [])}
    root = catalog.root.resolve()
    out: dict[str, bytes] = {}
    for item in entry.get("files") or []:
        rel = str(item.get("path") or "")
        if rel != "SKILL.md" and not safe_extra_path(rel):
            raise CatalogError(f"unsafe catalog path {rel!r}")
        upstream_rel = f"{entry['path']}/{rel}"
        row = recorded.get(upstream_rel)
        if row is None:
            raise CatalogError(f"{upstream_rel} is not in MANIFEST.json")
        target = catalog.root / upstream_rel
        current = catalog.root
        for part in PurePosixPath(upstream_rel).parts:
            current = current / part
            if current.is_symlink():
                raise CatalogError(f"{upstream_rel} is linked")
        try:
            target.resolve().relative_to(root)
            data = target.read_bytes()
        except (OSError, ValueError) as exc:
            raise CatalogError(f"{upstream_rel} cannot be read") from exc
        digest = hashlib.sha256(data).hexdigest()
        if not (hmac.compare_digest(digest, str(row.get("vendored_sha256")))
                and hmac.compare_digest(digest, str(row.get("upstream_sha256")))
                and hmac.compare_digest(digest, str(item.get("sha256")))
                and not row.get("rules_applied")):
            raise CatalogError(f"{upstream_rel} differs from MANIFEST.json")
        out[rel] = data
    if "SKILL.md" not in out:
        raise CatalogError("the catalog entry has no SKILL.md")
    return out


def provenance(catalog: Catalog, entry: dict, files: dict[str, bytes]) -> dict:
    commit = catalog.commit
    return {
        "source_repository": UPSTREAM_REPOSITORY,
        "source_commit": commit,
        "source_path": f"{entry['path']}/SKILL.md",
        "content_sha256": hashlib.sha256(files["SKILL.md"]).hexdigest(),
        "source_catalog": "vendored",
        "provenance": f"imported from Hermes @{commit[:8]}",
        "source_files": [{"path": rel, "sha256": hashlib.sha256(data).hexdigest()}
                         for rel, data in sorted(files.items())],
    }


async def install(importer, slug: str, *, root: Path | None = None) -> tuple[bool, InstallRefusal | None]:
    """Install one catalog skill through ``importer._save_skill``. ``(True, None)`` when it
    was written; ``(False, refusal)`` when the catalog refused it before the importer ran
    (``not_found``, ``upstream_only``, ``excluded``, ``catalog_unavailable``); ``(False,
    None)`` when the importer refused it — ``importer.outcome()`` then says why
    (``exists``, ``name_taken``, ``invalid_skill_md``), exactly as for any import."""
    from .importer import _safe_slug

    clean = _safe_slug(slug)
    if clean is None:
        return False, InstallRefusal("not_found")
    try:
        catalog = load(root)
    except CatalogError as exc:
        return False, InstallRefusal("catalog_unavailable", str(exc))
    entry = catalog.entry(clean)
    if entry is None:
        return False, InstallRefusal("not_found")
    if entry.get("kind") == KIND_UPSTREAM_ONLY:
        return False, InstallRefusal(
            "upstream_only", "this Hermes skill carries code; the catalog installs instructions only",
            tuple(f["path"] for f in entry.get("files") or [] if f.get("executable")))
    if entry.get("kind") != KIND_INSTRUCTION:
        return False, InstallRefusal("excluded", str(entry.get("reason") or ""))
    try:
        files = verified_files(catalog, entry)
    except CatalogError as exc:
        return False, InstallRefusal("catalog_unavailable", str(exc))
    raw = files["SKILL.md"]
    extras = {rel: data for rel, data in files.items() if rel != "SKILL.md"}
    ok = await importer._save_skill(
        clean, INSTALL_SOURCE, skill_md_text=raw.decode("utf-8"), skill_md_bytes=raw,
        provenance=provenance(catalog, entry, files), extra_files=extras,
    )
    return bool(ok), None
