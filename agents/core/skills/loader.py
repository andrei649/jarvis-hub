"""
loader.py — Skill Pack loader & procedural memory system.
A skill pack is a directory with SKILL.md + optional Python modules.
Agents can generate new skills from successful task completions.
"""

import hashlib
import importlib.machinery
import importlib.util
import json
import keyword
import logging
import re
import stat
import tempfile
import threading
import weakref
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from agents.core.automation_contracts import (
    ContractTemplate,
    contract_denial,
    field_present,
    one_of,
    predicate,
)

from . import frontmatter as _fm
from . import signing
from .approval import SkillApprovalStore

logger = logging.getLogger("jarvis.skills")

# Anchored on the app root (repo checkout in dev, PyInstaller bundle when
# frozen) instead of the CWD, so skill discovery works no matter where the
# process was launched from. From the repo root this is the same "skills/"
# directory as before.
from agents.core import load_set, safe_mode  # noqa: E402
from agents.core.paths import app_root as _app_root  # noqa: E402

SKILLS_DIR = _app_root() / "skills"
EXTERNAL_SOURCE_MARKER = "EXTERNAL_SOURCE"
# Legacy eligibility marker only. Candidate-controlled bytes inside a skill tree
# are never consulted as trust evidence (SEC-B8).
OWNER_APPROVED_MARKER = "OWNER_APPROVED_IN_PROCESS"

# H351 — the untrusted states the model-facing catalog still advertises.
#
# "unsigned" — the skill carries no ``SKILL.sig`` at all. That is the shipped default for
#     every bundled skill (``glob("skills/*/SKILL.sig")`` is empty), so dropping it would
#     empty the block and help nobody.
# "algo-mismatch" — a sidecar exists, but its algo prefix differs from the one this host
#     computes (``signing.verify_skill``/``compute_digest``: ``hmac-sha256`` when
#     ``JARVIS_SKILL_SIGNING_KEY`` is set, ``sha256`` when it is not). That is a fact about
#     *this host's key configuration at load time*, not about the SKILL.md bytes — sign a
#     tree with a key, then start the process without the variable, and every skill reports
#     "algo-mismatch" with sidecars and manifests byte-identical. Because the key is global
#     to the host it fires for all signed skills at once, so dropping it would blank the
#     model's whole skills index on a key rotation or a systemd unit that lost the variable.
#
# What still drops: "signature-mismatch" (the sidecar covers different bytes than the ones
# on disk) and "malformed-signature" (the sidecar is not a signature at all), plus any
# reason not listed here. Both mean: a sidecar is present and does not verify here. Neither
# is proof of intent — a truncated write produces the second, and a partially restored
# backup the first — so the gate is stated below for what it is.
#
# WHAT THIS GATE IS WORTH, plainly. It detects corruption and accidental drift in a skill
# that ships a sidecar; it does not stop a motivated attacker. Anyone with write access to a
# skill directory — exactly the access needed to edit SKILL.md in the first place — deletes
# ``SKILL.sig`` in the same operation, the skill then verifies as "unsigned", and it is
# advertised again on its new description (pinned by
# ``test_deleting_the_sidecar_evades_the_trust_gate``). Closing that needs two things this
# repo does not have yet: a signed skills tree, and a record kept OUTSIDE the tree of which
# skills were once seen signed, so a sidecar that disappears reads as a drop rather than as
# a reset to "unsigned". Until then this is a discovery hint, not an enforcement boundary.
CATALOG_TOLERATED_UNTRUSTED_REASONS = frozenset({"unsigned", "algo-mismatch"})


def _catalog_text(value: object, chars: int) -> str:
    """One line, capped, and with invisible-TAG payloads removed.

    Every field that lands inside a catalog row goes through this *before* it is scanned, so
    what ``quarantine.detect_injection`` sees is the literal text ``Agent.build_prompt`` will
    render. ``strip_invisible`` runs first because Unicode TAG characters (U+E0000–U+E007F)
    are not whitespace to ``str.split`` and are matched by no injection pattern: they render
    as nothing and carry an ASCII payload the model still reads (``quarantine`` module docs,
    Hermes absorption 4a). The tool-result and MCP paths already strip them on the way in;
    a SKILL.md frontmatter is the same kind of untrusted text headed for the same model.
    """
    from ..security import quarantine

    return " ".join(quarantine.strip_invisible(str(value)).split())[:chars]

# H326 — the model-facing skills index (Hermes ``build_skills_system_prompt``): one row a
# skill, name and description, grouped by category, rendered once per distinct input and
# kept in a small in-process LRU plus a disk snapshot validated by the skills' manifest hash.
INDEX_FORMAT = "nerva-skills-index/1"
INDEX_LRU_SIZE = 16
INDEX_SNAPSHOT_NAME = "skills_prompt_index.json"
#: A snapshot file larger than this is not read at all (it holds at most INDEX_LRU_SIZE blocks).
INDEX_SNAPSHOT_MAX_BYTES = 512 * 1024
INDEX_HEADER = "Available skills:"
INDEX_DEFAULT_CATEGORY = "general"
INDEX_MAX_COMMANDS = 8
#: H389 — under the coding posture (``visibility.coding_posture``) a non-coding category is
#: one line of names (Hermes ``  <category> [names only]: a, b``) and the index ends with
#: one of these notes (the first when ``skill_view`` is offered). Names are never hidden:
#: a skill the model stops seeing is a capability it stops reaching for.
INDEX_NAMES_ONLY = " [names only]: "
INDEX_NAMES_ONLY_NOTES = (
    "(Categories marked [names only] are outside the current coding context, so their descriptions "
    "are omitted - the skills work normally and load with skill_view(name) as usual.)",
    "(Categories marked [names only] are outside the current coding context, so their descriptions "
    "are omitted - the skills work normally.)",
)
_INDEX_LRU: "OrderedDict[str, str]" = OrderedDict()
_INDEX_LOCK = threading.Lock()


def _index_snapshot_path() -> Path:
    """Where the index snapshot lives: the profile's runtime-data root, never the repo."""
    from agents.core.paths import data_path

    return data_path(INDEX_SNAPSHOT_NAME)


def clear_index_cache() -> None:
    """Forget every in-process index block (the disk snapshot stays, still validated)."""
    with _INDEX_LOCK:
        _INDEX_LRU.clear()


def _skill_category(skill: "Skill") -> str:
    """The category a skill declares (``metadata.hermes.category``, or a top-level
    ``category``), lower-cased and one-lined; ``general`` when it declares none."""
    meta = getattr(skill, "hermes_meta", None) or {}
    raw = meta.get("category") if isinstance(meta, dict) else ""
    if not raw:
        manifest = getattr(skill, "manifest", None) or {}
        raw = manifest.get("category") if isinstance(manifest, dict) else ""
    return _catalog_text(raw if isinstance(raw, str) else "", 40).lower() or INDEX_DEFAULT_CATEGORY


# Product-owned identity of the exact skill sources shipped with this build.
# Unknown names, extra files, or changed bytes are external even when placed
# lexically under SKILLS_DIR. Text newlines are normalized so the same release
# identity works in Windows and POSIX checkouts; bytecode caches and top-level
# lifecycle controls are runtime products, not shipped source.
_BUNDLED_SKILL_MANIFEST: dict[str, dict[str, str]] = {
    "brief": {
        "SKILL.md": "795b049006d72fdf609c940eb2460b0b644f3f7aa9497c1a4a5dde473a44e88f",
        "main.py": "d0ff17b4bc5dbc29e97de38332400308eaffbf22440f99ee883dcefe35e27286",
    },
    "pm": {
        "SKILL.md": "b67bd2a0927713436f358baa12bce75c73ec224251c28e2931a51391e2e767a8",
        "main.py": "6bbfea103e7cfb1d43c1224e7c62febfb81fb569d77661cd370724e28d2e1dd9",
    },
    "security_monitor": {
        "SKILL.md": "959542c712e3ed1aa260870871156b692a3c9a4693decd5c95ba35665fc6dd5d",
        "main.py": "d781c8305a3307fba60de7e832e20576d55ef4ee03b5a30abd7796ab9bbbfea4",
    },
    "system_monitor": {
        "SKILL.md": "42b9c0a86723a8e6eb8d867951b2732d87047706ff850286216ab91ca2e70c6c",
        "main.py": "a7b483539973c9f1ea739615b89a70242d8ff7944687f25f50b92de80f289c41",
    },
    "weather": {
        "SKILL.md": "b4fc491c3c113ae3652cf81e95ef87e80d12b20be98253ad5239e0705e8774ff",
    },
}
_BUNDLED_IGNORED_CONTROLS = frozenset(
    {
        "SKILL.sig",
        "PENDING_REVIEW",
        OWNER_APPROVED_MARKER,
        EXTERNAL_SOURCE_MARKER,
    }
)


def _user_skills_dir() -> Optional[Path]:
    """The owner's personal skills root (Documents/Jarvis/skills), or None.

    Resolved at call time (not import) so tests/env changes are honored.
    """
    from agents.core.paths import user_skills_dir

    return user_skills_dir()


def _writable_skills_dir() -> Path:
    """Where NEW (generated/imported) skills are written.

    The bundled skills tree is shipped application content; anything personal
    goes to the user data home when one is active.
    """
    user_dir = _user_skills_dir()
    return user_dir if user_dir is not None else SKILLS_DIR


def _is_link_like(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if is_junction and is_junction():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        return bool(reparse and attributes & reparse)
    except OSError:
        return True


def _crosses_link_boundary(path: Path, root: Path) -> bool:
    """Treat linked/junction discovery roots and entries as external provenance."""
    path = Path(path).absolute()
    root = Path(root).absolute()
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    current = root
    if _is_link_like(current):
        return True
    for part in relative.parts:
        current = current / part
        if _is_link_like(current):
            return True
    try:
        resolved_path = path.resolve()
        resolved_root = root.resolve()
    except OSError:
        return True
    return resolved_path != resolved_root and resolved_root not in resolved_path.parents


def _matches_bundled_source(path: Path, root: Path) -> bool:
    """Match only exact product-owned source under the shipped discovery root."""
    try:
        resolved_path = path.resolve()
        resolved_root = root.resolve()
        if resolved_path.parent != resolved_root:
            return False
        snapshot = signing.source_snapshot(resolved_path)
    except OSError:
        return False
    return _snapshot_matches_bundled(snapshot, path.name)


def _shipped_location(path: Path) -> bool:
    """``path`` is where a shipped skill lives: directly under the product's skills tree,
    under a shipped skill's name. Its bytes may have drifted (so it loads as external),
    but it is still product source, never a place a patch writes (review-H318c n-6)."""
    try:
        return Path(path).resolve().parent == SKILLS_DIR.resolve() and Path(path).name in _BUNDLED_SKILL_MANIFEST
    except OSError:
        return False


def _snapshot_matches_bundled(
    snapshot: signing.SkillSourceSnapshot,
    skill_name: str,
) -> bool:
    expected = _BUNDLED_SKILL_MANIFEST.get(skill_name)
    if expected is None:
        return False
    actual: dict[str, str] = {}
    for item in snapshot.files:
        relative = Path(item.relative_path)
        if "__pycache__" in relative.parts:
            continue
        if len(relative.parts) == 1 and relative.name in _BUNDLED_IGNORED_CONTROLS:
            continue
        content = item.content.replace(b"\r\n", b"\n")
        actual[item.relative_path] = hashlib.sha256(content).hexdigest()
    return actual == expected


class _SourceOnlyLoader(importlib.machinery.SourceFileLoader):
    """Load validated source bytes without consulting candidate bytecode caches."""

    def get_code(self, fullname: str):
        source = self.get_data(self.path)
        return self.source_to_code(source, self.path)


def _is_external_skill(path: Path, *, discovery_root: Path | None = None) -> bool:
    """Return whether a skill came from outside the shipped skill tree."""
    lexical_path = Path(path)
    root = Path(discovery_root) if discovery_root is not None else SKILLS_DIR
    if _crosses_link_boundary(lexical_path, root):
        return True
    try:
        path = lexical_path.resolve()
    except OSError:
        return True
    user_dir = _user_skills_dir()
    if user_dir is not None:
        try:
            user_root = user_dir.resolve()
        except OSError:
            return True
        if path == user_root or user_root in path.parents:
            return True
    if (path / EXTERNAL_SOURCE_MARKER).is_file():
        return True

    sidecar = path / "manifest.json"
    if not sidecar.exists():
        return not _matches_bundled_source(path, root)
    try:
        json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        # An untrusted, malformed provenance sidecar cannot relax the boundary.
        return True
    # Bundled skills do not ship sidecars. Importers create this provenance file;
    # its presence stays external even if candidate-controlled fields are edited.
    return True


def _is_external_for_loader(
    path: Path,
    *,
    discovery_root: Path | None,
    approval_store: SkillApprovalStore,
) -> bool:
    """Classify using discovery evidence and durable private provenance."""
    return _is_external_skill(path, discovery_root=discovery_root) or approval_store.tracks_path(
        path
    )


_ORIGIN_RECORD_MAX = 64 * 1024


def _small_file(path: Path) -> Optional[bytes]:
    """The bytes of a regular, non-link file no larger than an install record, or None."""
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > _ORIGIN_RECORD_MAX:
            return None
        return path.read_bytes()
    except OSError:
        return None


def origin_evidence(skill: "Skill") -> tuple[Optional[str], str]:
    """H349 — where ``skill`` came from, as its own folder shows it: ``(origin, source)``.

    ``("bundled", "")``: it ships with Nerva (its bytes are the shipped ones, or it lives
    where a shipped skill lives and drifted). ``("import", source)``: its folder holds the
    record an install writes — the marketplace's ``EXTERNAL_SOURCE`` marker, or the
    ``manifest.json`` an import writes (``imported``, or a known ``source`` /
    ``source_install``) — with the source that record names. ``(None, "")``: no install
    record; whether the agent made it is the usage sidecar's creation-time marker, never
    read off the folder. The record is the one every install path already writes, so an
    install made while the hub was down is classified the same at the next start.

    The source is a label from a small vocabulary (review m2), since the record is a file
    anyone can edit and the label is shown to every user: ``marketplace`` only when the
    marketplace installer's own marker says exactly that, otherwise what
    ``usage.clean_source`` accepts (a known install source or a bare repository name) and
    ``""`` for anything else — never a URL, a path or free text."""
    from .usage import SOURCE_MARKETPLACE, clean_source

    path = Path(skill.path)
    if not getattr(skill, "external", True):
        return "bundled", ""
    marker = _small_file(path / EXTERNAL_SOURCE_MARKER)
    if marker is not None:
        source = ""
        for line in marker.decode("utf-8", "replace").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "source":
                source = SOURCE_MARKETPLACE if value.strip() == SOURCE_MARKETPLACE else ""
                break
        return "import", source
    sidecar = _small_file(path / "manifest.json")
    if sidecar is not None:
        try:
            data = json.loads(sidecar.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            install, source = data.get("source_install"), data.get("source")
            if isinstance(install, str) and install.strip():
                return "import", clean_source(install)
            if data.get("imported") is True or source in ("hermes", "openclaw"):
                return "import", clean_source(source)
    if _shipped_location(path):
        return "bundled", ""
    return None, ""


def skill_roots() -> list[Path]:
    """Every folder skills are discovered in, in discovery order: the app-root skills tree,
    then the owner's skills folder when one is active. THE list: ``discover()`` reads these
    (minus the owner's in safe mode), and the name check of every creation path scans
    these — one list, so no caller can look at fewer roots than the loader loads from."""
    roots = [SKILLS_DIR]
    user_dir = _user_skills_dir()
    try:
        if user_dir is not None and user_dir.is_dir() and user_dir.resolve() != SKILLS_DIR.resolve():
            roots.append(user_dir)
    except OSError:
        pass
    return roots


_NAME_PARSER: "SkillLoader | None" = None
#: The loader that discovered last (a weak reference): its registry is what is loaded now.
_LIVE_LOADER: "weakref.ReferenceType | None" = None


def loader_name(folder, source_bytes: bytes | None = None) -> str:
    """The name the loader registers the skill in ``folder`` under — by the loader's own
    parse of its SKILL.md (``source_bytes``, or the file) — or ``""`` when it cannot be
    read. The one naming used to compare a new skill with the ones installed."""
    global _NAME_PARSER
    if _NAME_PARSER is None:
        _NAME_PARSER = SkillLoader.__new__(SkillLoader)      # the parse methods keep no state
    folder = Path(folder)
    try:
        manifest = _NAME_PARSER._parse_manifest(folder / "SKILL.md", source_bytes=source_bytes)
        return str(manifest.get("name", folder.name))
    except Exception:
        return ""


def _id_less_holder(name: str) -> bool:
    """Whether an installed folder with no install id (the owner's own, agent-made or a
    legacy install) still declares ``name``, in any root. An unreadable root counts as yes:
    a row is never forgotten on what could not be seen."""
    for root in skill_roots():
        try:
            folders = [entry for entry in root.iterdir() if entry.is_dir()]
        except OSError:
            return True
        for folder in folders:
            if loader_name(folder) == name and not install_id_of(folder):
                return True
    return False


def name_holder(name: str, *, except_dir=None, extra_roots=(), registry=None) -> Optional[Path]:
    """H349 — the folder of an installed skill that already holds ``name``, other than
    ``except_dir`` (the folder the new skill goes into); None when the name is free.

    Names are compared exactly, as the registry keys them: ``spotify`` and ``Spotify`` are
    two names to the loader, so they are two names here (fifth review). And a skill that
    ships with Nerva is not a holder for a folder that goes into another root: a skill of
    the owner's named like a bundled one is by design (``discover()`` loads the owner's
    folder after the app root so that it wins the name).

    THE holder check, asked by every path that creates a skill before it writes anything
    (an import, a marketplace install, the local migration, a batch create, generation):
    a new skill under a held name would take that skill's registry slot — the loader lets
    a later folder take a name — while the holder's folder stays where it is. It looks at

    - the live registry (``registry``, else the loader that discovered last), so a skill
      that is loaded counts even when its folder cannot be listed right now, and
    - every folder under every root the loader discovers (:func:`skill_roots`, plus the
      caller's own root in ``extra_roots``), named by the loader's own parse
      (:func:`loader_name`), so a skill that is installed but not loaded — the owner's
      load set, safe mode, a failed load — counts too, whichever root it lives in.
    """
    wanted = name.strip() if isinstance(name, str) else ""
    if not wanted:
        return None
    try:
        skip = Path(except_dir).resolve() if except_dir is not None else None
        elsewhere = skip is not None and skip.parent != SKILLS_DIR.resolve()
    except OSError:
        skip, elsewhere = None, False

    def _other(folder: Path) -> bool:
        try:
            # A bundled skill does not hold its name against another root. An import or an
            # install that sits at a shipped location (it carries an install record) is not
            # bundled: it holds its name like any other skill (sixth review).
            if (elsewhere and _shipped_location(folder) and not install_id_of(folder)
                    and not (folder / "manifest.json").is_file()):
                return False
            return skip is None or folder.resolve() != skip
        except OSError:
            return True

    if registry is None and _LIVE_LOADER is not None:
        live = _LIVE_LOADER()
        registry = getattr(live, "skills", None)
    for held, skill in list((registry or {}).items()):
        folder = Path(getattr(skill, "path", "") or "")
        if str(held) == wanted and _other(folder) and folder.is_dir():
            return folder
    seen: set[str] = set()
    for base in [*skill_roots(), *[Path(r) for r in extra_roots]]:
        try:
            key = str(base.resolve())
            if key in seen:
                continue
            seen.add(key)
            folders = sorted(base.iterdir())
        except OSError:
            continue
        for folder in folders:
            try:
                if folder.name.startswith(".") or not folder.is_dir() or not _other(folder):
                    continue
                if _small_file(folder / "SKILL.md") is None and not (folder / "SKILL.md").is_file():
                    continue
            except OSError:
                continue
            if loader_name(folder) == wanted:
                return folder
    return None


def install_id_of(folder: Path) -> str:
    """H349 — the install id the install that made ``folder`` stamped into it, or ``""``:
    the ``install=`` line of the marketplace's ``EXTERNAL_SOURCE`` marker, or the
    ``install_id`` of an import's ``manifest.json``. It is what makes a new install
    recognisable whenever the hub first sees it — in the same request, after a crash, at
    the start after an offline import — without anything kept in memory. A folder from
    before the id existed, the owner's own skill and an agent-made one carry none."""
    from .usage import clean_install_id

    marker = _small_file(Path(folder) / EXTERNAL_SOURCE_MARKER)
    if marker is not None:
        for line in marker.decode("utf-8", "replace").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "install":
                return clean_install_id(value.strip())
        return ""
    sidecar = _small_file(Path(folder) / "manifest.json")
    if sidecar is not None:
        try:
            data = json.loads(sidecar.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            return ""
        if isinstance(data, dict):
            return clean_install_id(data.get("install_id"))
    return ""


def _external_skill_may_import(
    path: Path,
    signature_reason: str,
    approval_store: SkillApprovalStore,
    snapshot: signing.SkillSourceSnapshot,
) -> bool:
    return (
        signature_reason == "signed"
        or approval_store.approved_snapshot(
            path,
            snapshot=snapshot,
        )
        is not None
    )


#: What skill_view may keep of a skill (H318): a file up to VIEW_FILE_BYTES is kept as
#: bytes, and at most VIEW_SKILL_BYTES of a skill in all; any other file is kept as its
#: size, so it is listed and refused as too large rather than held in memory.
VIEW_FILE_BYTES = 64 * 1024
VIEW_SKILL_BYTES = 1024 * 1024


def _view_files(snapshot: "signing.SkillSourceSnapshot | None") -> dict[str, "bytes | int"]:
    out: dict[str, bytes | int] = {}
    kept = 0
    for item in getattr(snapshot, "files", ()) or ():
        if item.kind != "file":
            continue
        size = len(item.content)
        if size <= VIEW_FILE_BYTES and kept + size <= VIEW_SKILL_BYTES:
            out[item.relative_path] = bytes(item.content)
            kept += size
        else:
            out[item.relative_path] = size
    return out


def _materialize_source_snapshot(
    snapshot: signing.SkillSourceSnapshot,
) -> tuple[tempfile.TemporaryDirectory, Path]:
    """Write validated bytes to a private tree retained with the loaded module."""
    holder = tempfile.TemporaryDirectory(prefix="jarvis-skill-snapshot-")
    root = Path(holder.name)
    try:
        for item in snapshot.files:
            target = root.joinpath(*Path(item.relative_path).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(item.content)
    except Exception:
        holder.cleanup()
        raise
    return holder, root


# Generated command names become both a Python `def` and a `\w+` token in SKILL.md.
_MAX_COMMAND_NAME = 64


def _safe_command_name(raw: Optional[str], fallback: str) -> str:
    """Coerce an untrusted command name into a bare Python identifier.

    ``command_name`` reaches `generate_skill` straight from LLM output — the third field
    of a ``[learn:task|steps|cmd]`` block (`orchestrator.py`) — and is substituted into
    generated Python source. Anything outside ``[A-Za-z_][A-Za-z0-9_]*`` would write a
    module that cannot parse, or one shaped by whatever the model emitted. The manifest
    parser is equally strict (``## Commands`` entries are matched as ``\\w+``), so a
    sanitized name is also the only one that can round-trip through SKILL.md.

    Call this *after* `quarantine.detect_injection` has seen the raw value — sanitizing
    first would turn "ignore previous instructions" into a name the scanner no longer
    recognizes.
    """
    for candidate in (raw, fallback):
        name = re.sub(r"_+", "_", re.sub(r"\W", "_", str(candidate or "").strip()))
        name = name.strip("_")[:_MAX_COMMAND_NAME].strip("_")
        if not name:
            continue
        if name[0].isdigit():
            name = f"cmd_{name}"
        if name.isidentifier() and not keyword.iskeyword(name):
            return name
    return "run"


def _generated_skill_name_safe(view, now) -> bool:
    name = str(view.get("name") or view.get("command_name") or "").strip()
    return bool(
        name
        and name not in (".", "..")
        and "/" not in name
        and "\\" not in name
        and "\x00" not in name
    )


def _skill_generation_contract_template() -> ContractTemplate:
    return ContractTemplate(
        kind="skill.generation",
        description="LLM-authored skill creation and owner-promotion gate.",
        constraints=(
            field_present("action", "agent"),
            one_of("action", {"generate", "approve"}),
            predicate(
                "generated_skill_name_safe", _generated_skill_name_safe, reason="invalid_skill_name"
            ),
        ),
    )


SKILL_GENERATION_CONTRACT_KIND = "skill.generation"
SKILL_GENERATION_CONTRACT = _skill_generation_contract_template()


def _skill_generation_allowed(payload: dict) -> bool:
    try:
        decision = SKILL_GENERATION_CONTRACT.evaluate(payload)
    except Exception:
        logger.warning("skill generation contract evaluation failed", exc_info=True)
        return False
    reason = contract_denial(decision)
    if reason:
        logger.warning("Skill generation blocked by contract: %s", reason)
        return False
    return True


def _split_frontmatter(content: str) -> tuple[Optional[dict], str]:
    """Split a SKILL.md into (yaml_frontmatter_dict, body).

    Returns (None, content) when there is no ``---`` frontmatter block, so callers
    can fall back to the Markdown-heading dialect. The parse is the shared H327
    contract: a leading BOM is dropped and malformed YAML falls back to
    ``key: value`` lines (``frontmatter.split_frontmatter``).
    """
    return _fm.split_frontmatter(content)


def _scrubbed_error(exc: BaseException, secrets: tuple) -> str:
    """An exception's text with the skill's own stored values taken out (H342)."""
    if not secrets:
        return str(exc)
    from .skill_secrets import scrub

    return scrub(str(exc), secrets)


class Skill:
    def __init__(self, name: str, path: Path, manifest: dict):
        self.name = name
        self.path = path
        self.manifest = manifest
        self.module = None
        self.commands: dict[str, Callable] = {}
        # H12.1 — signature/trust metadata (advisory by default).
        self.trusted: bool = False
        self.signature_reason: str = "unsigned"
        # Sandboxed = untrusted code whose Python module was NOT exec'd in-process.
        self.sandboxed: bool = False
        # H20.5 — best-effort usage-telemetry hook (set by SkillLoader.attach_usage);
        # None keeps execute() byte-identical to today's behavior.
        self.usage_hook: Optional[Callable] = None
        # H318 — what skill_view serves: the files of the snapshot the trust checks ran on
        # (a later edit on disk is not what was verified), each kept as bytes when it is
        # small enough to serve and as its size otherwise (VIEW_FILE_BYTES each,
        # VIEW_SKILL_BYTES a skill), so a skill's assets are not held for the process's life.
        self.view_files: dict[str, bytes | int] = {}
        # Whether the source is from outside the product (an import, the owner's own tree),
        # and whether the owner vouched for it: a keyed signature or an owner approval of
        # these exact bytes. An unkeyed SKILL.sig is a sha256 anyone can compute, so it is
        # not a vouch (review-H318 M-1, SEC-B2). A bundled skill is the product's own.
        self.external: bool = True
        self.owner_vouched: bool = False
        # Exact bytes admitted at load time; approval must match both these and disk.
        self.source_fingerprint: str | None = None

    def to_dict(self) -> dict:
        from .visibility import readiness

        ready, why = readiness(self)
        return {
            "readiness": ready,
            "readiness_reason": why,
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "agents": self.agents,
            "trusted": self.trusted,
            "signature_reason": self.signature_reason,
            "sandboxed": self.sandboxed,
            "has_module": self.module is not None,
            "platforms": self.platforms,
            "environments": self.environments,
            "requires_apps": self.requires_apps,
            "required_env": self.required_env,
            # H342: the required names set nowhere (never a value).
            "setup_needed": self._setup_needed(),
            "hermes": self.hermes_meta,
        }

    def _setup_needed(self) -> list[str]:
        if not self.required_env:
            return []
        from . import skill_secrets

        return skill_secrets.missing(self)

    @property
    def description(self) -> str:
        return self.manifest.get("description", "")

    @property
    def author(self) -> str:
        return self.manifest.get("author", "unknown")

    @property
    def version(self) -> str:
        return self.manifest.get("version", "0.1.0")

    @property
    def requires(self) -> list[str]:
        return self.manifest.get("requires", [])

    @property
    def agents(self) -> list[str]:
        return self.manifest.get("agents", [])

    @property
    def commands_meta(self) -> list[dict]:
        return self.manifest.get("commands", [])

    # H327 — the contract fields a SKILL.md declared (empty for the heading dialect).
    @property
    def platforms(self) -> list[str]:
        return list(self.manifest.get("platforms", []))

    @property
    def environments(self) -> list[str]:
        return list(self.manifest.get("environments", []))

    @property
    def requires_apps(self) -> list[str]:
        return list(self.manifest.get("requires_apps", []))

    @property
    def required_env(self) -> list[str]:
        """Names of the environment variables the skill declares; never their values."""
        return [e["name"] for e in self.manifest.get("required_environment_variables", [])
                if isinstance(e, dict) and e.get("name")]

    @property
    def hermes_meta(self) -> dict:
        return dict(self.manifest.get("hermes", {}))

    def register_command(self, name: str, fn: Callable):
        self.commands[name] = fn

    async def execute(self, command: str, args: str = "", context: dict = None) -> str:
        from . import switches

        # H329: a switched-off skill stays installed and is not run; the turn is told why.
        off = switches.off_reason(self, (context or {}).get("channel"))
        if off:
            logger.info("Skill '%s' is switched off %s; command '%s' refused", self.name, off, command)
            return switches.refusal(self, off)
        from .visibility import readiness

        # H328: a skill for another operating system cannot run here, even when named. Only
        # code that would run is refused: a skill with none (quarantined, Markdown only)
        # answers "" as before, and the turn goes on to the model.
        cmd_fn = self.commands.get(command)
        runnable = bool(cmd_fn) or bool(self.module and hasattr(self.module, "handle"))
        ready, why = readiness(self) if runnable else ("ready", "")
        secrets: tuple = ()     # H342: this call's own stored values, scrubbed from its errors
        if ready != "ready":
            logger.info("Skill '%s' is %s; command '%s' refused", self.name, why, command)
            return f"[skill:{self.name}] is {why}"
        if runnable and self.required_env:
            # H496 (review M1): a skill that declares credentials runs on the owner's — its
            # stored setup values, or the same names from the hub's own environment, which
            # its code reads. A guest turn runs it only when the owner shared the skill.
            # Every path that runs a skill command (the model's tools, a plain-text
            # ``skill command`` dispatched by the orchestrator) comes through here.
            from agents.core.security.credential_scope import KIND_SKILL, allowed

            if not allowed(KIND_SKILL, self.name):
                logger.warning("Skill '%s' refused: its credentials are not shared with guests",
                               self.name)
                return (f"[skill:{self.name}] uses the owner's credentials, which are not "
                        "shared with guests")
            # H342: a runnable skill whose required variables are set nowhere does not run.
            from . import skill_secrets

            unset = skill_secrets.missing(self)
            if unset:
                logger.info("Skill '%s' needs setup (%d variable(s)); command '%s' refused",
                            self.name, len(unset), command)
                return skill_secrets.setup_message(self.name, unset)
            stored = skill_secrets.skill_env(self)
            secrets = tuple(stored.values())
            if stored and (context or not cmd_fn):
                # Its own stored values only, read-only, for this call; never os.environ.
                # (A command called without a context keeps its one-argument call.)
                context = {**(context or {}), "skill_env": stored}
        if self.usage_hook is not None:
            try:
                self.usage_hook(self.name, "use")
            except Exception:
                logger.debug("usage hook failed for %s", self.name, exc_info=True)
        if cmd_fn:
            try:
                if context:
                    return await cmd_fn(args, context)
                return await cmd_fn(args)
            except Exception as e:
                detail = _scrubbed_error(e, secrets)
                logger.error("Skill %s command '%s' failed: %s", self.name, command, detail)
                return f"[skill:{self.name}] error: {detail}"

        if self.module and hasattr(self.module, "handle"):
            try:
                return await self.module.handle(command, args, context or {})
            except Exception as e:
                detail = _scrubbed_error(e, secrets)
                if secrets:
                    # A traceback would carry the skill's own values (H342): message only, scrubbed.
                    logger.warning("Skill '%s' handle() raised for command '%s': %s: %s",
                                   self.name, command, type(e).__name__, detail)
                else:
                    logger.warning(
                        "Skill '%s' handle() raised for command '%s'", self.name, command, exc_info=True
                    )
                return f"[skill:{self.name}] error: {detail}"

        return ""


class SkillLoader:
    #: H330 — the class-level defaults of the two attributes below, for a loader built
    #: without ``__init__`` (tests do): the live hub's gate, and no refusal yet.
    kernel_gate = None
    last_approval_refusal: str = ""

    def __init__(self, approval_store: SkillApprovalStore | None = None):
        self.skills: dict[str, Skill] = {}
        # H350 — why the last generate_skill refused its document (empty when it did not).
        self.last_generation_problems: list = []
        # H507 — what the last generated skill's code looks like (warn-only).
        self.last_generation_warnings: list = []
        # H330 — why the last approve_generated_skill refused at the action kernel
        # ("kernel_denied" / "kernel_error"; empty when it did not).
        self.last_approval_refusal: str = ""
        # H330 — the ``skill.generation`` kernel gate a generated skill and its promotion
        # cross (acquisition.promotion.make_skill_generation_kernel_gate). None binds the
        # live hub's kernel at call time; the action-auth matrix injects its own.
        self.kernel_gate = None
        # H20.5 — optional usage-telemetry sidecar (SkillUsageStore); attached by
        # the orchestrator. None → zero behavior change.
        self._usage = None
        # H349: set while discover() walks the roots (origins are recorded once, at its end).
        self._discovering = False
        # What a creation in progress must put back in the usage sidecar if it fails.
        self._creation_undo = None
        self._approval_store = approval_store or SkillApprovalStore()

    def _generation_kernel_refusal(self, payload: dict, *, title: str) -> str:
        """Cross the ``skill.generation`` kernel gate: ``""`` to proceed, else why not."""
        from agents.core.acquisition.promotion import cross_skill_gate, hub_skill_kernel_gate

        gate = self.kernel_gate or hub_skill_kernel_gate(SKILL_GENERATION_CONTRACT_KIND, title=title)
        return cross_skill_gate(gate, {"kind": SKILL_GENERATION_CONTRACT_KIND, **payload})

    def attach_usage(self, store) -> None:
        """Attach a SkillUsageStore; hooks existing and future skills."""
        self._usage = store

        def _hook(name: str, kind: str) -> None:
            store.bump(name, kind)

        for skill in self.skills.values():
            skill.usage_hook = _hook
        self.sync_origins()

    def sync_origins(self, names=None, *, strict: bool = False) -> None:
        """H349 — record in the usage sidecar where each registered skill came from
        (:func:`origin_evidence`): every one, or just ``names``. Called when the sidecar is
        attached, at the end of every discovery pass and whenever a skill takes a registry
        slot outside one, which every install path crosses (import, marketplace,
        generation, a batch, a start after an offline install), so no path has to remember
        to record it. The sidecar writes only rows that changed.

        Only what is seen is reported (second review, B1/B2). A skill is reported by its
        name, its install record, the fingerprint of its bytes and the install id its
        folder carries (:func:`install_id_of`) — never by where its folder is, and with
        nothing remembered from an earlier call: whether a skill is new is written at its
        creation, in the sidecar or in the folder (third review, M1). A skill that is not
        seen now (its folder moved, missing, unreadable, on a volume that is away) is
        simply not reported: its row is left exactly as it is, and the sidecar is only
        told the name is not registered.

        Two steps: :meth:`observe` reads the folders, taking no lock, and :meth:`record`
        writes what was seen under the sidecar's lock. A caller that must hold that lock
        across the write and something else (the pin route) calls them itself, so the
        slow part — reading a folder — never runs inside the hold.

        Best-effort like the counters: a sidecar that cannot be written leaves loading
        alone, and the row is tried again at the next registration. ``strict`` raises
        instead, for a caller that is about to rely on the row (the pin route)."""
        self.record(self.observe(names, strict=strict), full=names is None, strict=strict)

    def observe(self, names=None, *, strict: bool = False) -> dict:
        """What the folders of the registered skills ``names`` (or all) show now: name →
        ``(origin, source, fingerprint, {"install_id": …})``. Reads files and takes no
        lock. A skill whose folder is not there is left out (and, for a single name, the
        sidecar is told it is not registered — its row is not touched)."""
        store = self._usage
        if not callable(getattr(store, "reconcile_origins", None)):
            return {}
        full = names is None
        observed = {}
        for name in (list(self.skills) if full else names):
            skill = self.skills.get(name)
            if skill is None:
                continue
            try:
                folder = Path(skill.path)
                if not folder.is_dir():
                    # Not there now. That is not a removal: the row stays as it is.
                    unregister = getattr(store, "unregister", None)
                    if not full and callable(unregister):
                        unregister(name)
                    continue
                origin, source = origin_evidence(skill)
                observed[name] = (origin, source, self._fingerprint_of(skill, folder),
                                  {"install_id": install_id_of(folder)})
            except Exception:
                if strict:
                    raise
                logger.warning("the origin of skill %r could not be read", name, exc_info=True)
        return observed

    def record(self, observed: dict, *, full: bool = False, strict: bool = False) -> None:
        """Write what :meth:`observe` saw into the usage sidecar (one lock, one write)."""
        reconcile = getattr(self._usage, "reconcile_origins", None)
        if not callable(reconcile) or (not observed and not full):
            return

        def _still_there(name) -> bool:
            # Asked under the sidecar's lock: a removal that landed since the look
            # must not be undone by this observation.
            seen = self.skills.get(name)
            return seen is not None and Path(seen.path).is_dir()

        try:
            try:
                reconcile(observed, full=full, verify=_still_there)
            except TypeError:
                reconcile(observed, full=full)        # a stand-in store without ``verify``
        except Exception:
            if strict:
                raise
            logger.warning("skill origins could not be recorded in the usage sidecar", exc_info=True)

    @staticmethod
    def _fingerprint_of(skill: "Skill", folder: Path) -> str:
        """The fingerprint of the skill's bytes: the one its load took, or — for a skill
        that loads without one (awaiting review) — computed from the folder now, so its
        row can be matched to these bytes later (a restore from the archive)."""
        known = getattr(skill, "source_fingerprint", None)
        if isinstance(known, str) and known:
            return known
        return SkillLoader.folder_fingerprint(folder)

    @staticmethod
    def folder_fingerprint(folder) -> str:
        """The fingerprint of the bytes in ``folder``, or ``""`` when it cannot be read."""
        try:
            return signing.source_snapshot(Path(folder)).fingerprint or ""
        except Exception:
            logger.debug("no fingerprint for the skill at %s", folder, exc_info=True)
            return ""

    def mark_new(self, folder) -> None:
        """H349 — a skill was just created in ``folder`` by a caller that has no other way
        to say so (the installs stamp an install id, generation and a batch create write
        the row themselves): settle its row now, from the folder as it is — fresh, never
        pinned, not agent-made, counters kept only for the bytes the row last saw
        (``SkillUsageStore.settle_created``). Decided and written here, at creation;
        nothing is kept in memory for a later registration. A name whose holder is
        installed in another folder is left alone. Logged when it cannot be written."""
        settle = getattr(self._usage, "settle_created", None)
        if not callable(settle):
            return
        folder = Path(folder)
        try:
            name = self.manifest_name(folder, (folder / "SKILL.md").read_text(encoding="utf-8"))
            holder = self.skills.get(name)
            if holder is not None and Path(holder.path).is_dir() and Path(holder.path).resolve() != folder.resolve():
                return
            settle(name, self.folder_fingerprint(folder))
        except Exception:
            logger.warning("the usage row of the new skill in %s could not be started", folder.name, exc_info=True)

    def forget_usage(self, name: str, install_id: str | None = None) -> None:
        """H349 — an explicit removal for good of the skill registered as ``name`` (a
        reject from review, an uninstall): its sidecar row goes with it
        (``SkillUsageStore.forget``). ``install_id`` names which install's row, when
        several folders have held the name. Only removal acts call this; a skill that is
        merely not seen keeps its row. Logged when it cannot be written (the sidecar then
        keeps the removal pending and applies it at its next writable sync).

        H342: the skill's stored setup values go too (only that install's, when named)."""
        try:
            from . import skill_secrets

            skill_secrets.forget_skill(name, install_id)
        except Exception:
            logger.warning("the setup values of the removed skill %r could not be cleared", name)
        forget = getattr(self._usage, "forget", None)
        if not callable(forget):
            return
        try:
            if install_id is None:
                forget(name)
            else:
                forget(name, install_id)
        except Exception:
            logger.warning("the usage row of the removed skill %r could not be retired", name, exc_info=True)

    def forget_removed(self, name: str, install_id: str = "") -> bool:
        """H349 (fourth review, M3) — the folder of a skill named ``name`` was just removed
        for good. Its own row goes; a row that belongs to another folder that still holds
        the name does not: an install has a row of its own (by its install id), and a
        folder without an id shares its row only with other id-less folders of that name,
        so that row is left when one of those is still installed. Says whether another
        holder remains (the caller then re-discovers, so it takes the slot)."""
        other = name_holder(name, registry=self.skills) if name else None
        # An id-less folder's row also goes when nothing id-less is left for it to describe
        # (fifth review, m1) — decided over EVERY remaining folder of the name, not the first
        # holder: another id-less folder may sit behind an install with an id, and forgetting
        # on the first holder alone cost the owner a pin (sixth review).
        if other is None or install_id or not _id_less_holder(name):
            self.forget_usage(name, install_id if other is not None else None)
        return other is not None

    def approval_times(self, paths) -> dict[str, str]:
        """H046 — when the owner last approved each skill folder in ``paths`` (ISO), keyed by
        the path as given: the approval of a generated skill, or of a patch's bytes. Read
        only to date what was learned, never to decide trust."""
        return self._approval_store.approved_times(paths)

    def note_usage(self, name: str, kind: str) -> None:
        """H354 — count one ``view`` or ``patch`` of a skill in the attached sidecar.

        ``use`` is counted by the skill's own hook when it runs; the reads (``skill_view``)
        and edits (the owner's batch route, an approved batch) that never run it come
        through here. Best-effort like that hook: no sidecar attached, or a broken one,
        is a no-op and never fails the call that asked."""
        store = self._usage
        if store is None:
            return
        try:
            store.bump(name, kind)
        except Exception:
            logger.debug("usage note skipped for %s/%s", name, kind, exc_info=True)

    def revoke_approval(self, path) -> bool:
        """Drop the owner approval bound to ``path`` (DRA-54).

        A seam so callers holding the orchestrator (e.g. the marketplace
        uninstall route) never reach into the approval store directly.
        """
        try:
            return self._approval_store.revoke(Path(path))
        except Exception:
            logger.warning("Skill approval revoke failed for %s", path, exc_info=True)
            return False

    def discover(self):
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        # DRA-54 — self-heal approvals whose skill directory was removed out of
        # band. Never fatal: a store failure must not break skill discovery.
        try:
            self._approval_store.prune_missing()
        except Exception:
            logger.warning("Skill approval prune failed", exc_info=True)
        global _LIVE_LOADER
        _LIVE_LOADER = weakref.ref(self)
        roots = skill_roots()
        owner_unread = False
        # The owner's personal skills (Documents/Jarvis/skills) load AFTER the
        # bundled tree so a same-named user skill wins the registry slot.
        if len(roots) > 1 and safe_mode.enabled():
            # H275: safe mode discovers the shipped skills only.
            safe_mode.note("owner_skills")
            owner_unread = True
            roots = roots[:1]
        # H285: the owner's load set, read once for this pass.
        load_set.begin("skills")
        self._load_lists = load_set.declared("skills")
        folders: set[str] = set()
        self._discovering = True
        try:
            for root in roots:
                for skill_dir in sorted(root.iterdir()):
                    if skill_dir.is_dir():
                        folders.add(skill_dir.name)
                        try:
                            self._load_skill(skill_dir, discovery_root=root)
                        except signing.SkillSigningMisconfigured:
                            raise  # SEC-B2: the operator has to see this one
                        except Exception:
                            # One hostile or unreadable SKILL.md must not take the rest of
                            # discovery (and startup) down with it; it simply is not registered.
                            logger.warning("Skill at %s could not be loaded; skipped", skill_dir, exc_info=True)
            if not owner_unread:
                # With the owner folder left unread (safe mode), a name that matches no
                # shipped skill may name an installed one of the owner's: not "unknown".
                load_set.finish("skills", folders | set(self.skills) | set(load_set.status("skills")["skipped"]),
                                lists=self._load_lists)
        finally:
            # A later single-skill load (sign, approve) reads the lists as they are then.
            self._load_lists = None
            self._discovering = False
        # H349: one pass over the sidecar — every registered skill's origin. Rows of skills
        # this pass did not see are left as they are.
        self.sync_origins()
        logger.info(f"Skills loaded: {list(self.skills.keys())}")
        return self.skills

    def _register(self, name: str, skill: "Skill") -> None:
        """Put ``skill`` in the registry slot ``name``, saying so when it replaces another.

        A user skill replacing a bundled one of the same name is by design (info). Two
        skills of one tree claiming one name — e.g. two names that share their first 64
        characters, the agentskills.io cap — is a collision the owner should see.
        """
        previous = self.skills.get(name)
        if previous is not None and Path(previous.path) != Path(skill.path):
            same_tree = Path(previous.path).parent == Path(skill.path).parent
            (logger.warning if same_tree else logger.info)(
                "Skill name '%s' from %s replaces the one from %s", name, skill.path, previous.path)
        self.skills[name] = skill
        # H349: the registry slot is the one place every installed skill passes. A
        # discovery pass records all of them once, at its end.
        if not self._discovering:
            self.sync_origins([name])

    def _load_skill(self, path: Path, *, discovery_root: Path | None = None):
        # H32.5: acquired packages are signed for integrity but are NEVER trusted
        # for in-process import. Their only execution path is the acquired Docker/
        # WASM runner registered through ToolRPC.
        if (path / "ACQUIRED_SANDBOX_ONLY").exists():
            logger.warning("Refused in-process discovery of sandbox-only acquired package")
            return
        skill_file = path / "SKILL.md"
        if not skill_file.exists():
            return

        external = _is_external_for_loader(
            path,
            discovery_root=discovery_root,
            approval_store=self._approval_store,
        )
        snapshot: signing.SkillSourceSnapshot | None = None
        if not (path / "PENDING_REVIEW").exists():
            try:
                snapshot = signing.source_snapshot(path)
            except OSError:
                logger.warning(
                    "Skill source snapshot failed closed",
                    exc_info=True,
                )
        if not external and snapshot is not None:
            external = not _snapshot_matches_bundled(snapshot, path.name)
        if external and safe_mode.enabled():
            # H275: a generated, imported, edited or pending-review skill in the bundled
            # tree is the owner's, not the release's; safe mode leaves it out entirely.
            safe_mode.note("owner_skills")
            logger.info("Safe mode: skill at %s is not a shipped skill; not loaded", path.name)
            return

        snapshot_manifest = snapshot.read_bytes("SKILL.md") if snapshot else None
        manifest = self._parse_manifest(skill_file, source_bytes=snapshot_manifest)
        name = manifest.get("name", path.name)
        lists = getattr(self, "_load_lists", None)
        if not load_set.permits("skills", name, path.name, lists=lists):
            # H285: switched off by the owner's load set; nothing about it is registered,
            # and a registration from an earlier pass over this folder is taken out.
            previous = self.skills.get(name)
            if previous is not None and Path(previous.path) == path:
                del self.skills[name]
            load_set.note_skipped("skills", name)
            return
        skill = Skill(name, path, manifest)
        skill.source_fingerprint = snapshot.fingerprint if snapshot is not None else None
        skill.external = bool(external)
        if self._usage is not None:
            store = self._usage
            skill.usage_hook = lambda n, kind: store.bump(n, kind)

        # CDX-8: a quarantined auto-generated skill (pending owner review) is registered so
        # it's visible/reviewable, but its module is NEVER exec'd in-process until approved —
        # fail-closed regardless of the signature-enforcement env.
        if (path / "PENDING_REVIEW").exists():
            skill.trusted = False
            skill.sandboxed = True
            skill.signature_reason = "pending review (CDX-8 quarantine)"
            self._register(name, skill)
            logger.info("Skill '%s' is PENDING REVIEW — NOT loaded in-process (quarantined)", name)
            return

        if snapshot is None:
            skill.trusted = False
            skill.sandboxed = True
            skill.signature_reason = "source-snapshot-invalid"
            self._register(name, skill)
            logger.warning(
                "Skill '%s' source was not a stable regular-file snapshot — "
                "module NOT loaded in-process",
                name,
            )
            return

        # H12.1 — verify signature (advisory). Unsigned/invalid skills load but
        # are flagged untrusted; when JARVIS_REQUIRE_SIGNED_SKILLS=1 their Python
        # module is not exec'd in-process (sandboxed/flagged instead).
        skill.trusted, skill.signature_reason = signing.verify_skill(
            path,
            snapshot=snapshot,
        )
        # SEC-B2: raises when enforcement is on with no signing key — a gate that cannot
        # tell an attacker's signature from ours must stop the load rather than wave it
        # through. Deliberately NOT caught here: the operator has to see it.
        require_signed = signing.require_signed()

        snapshot_main = snapshot.read_bytes("main.py") if snapshot else None
        py_exists = snapshot_main is not None
        external_import_allowed = not external or _external_skill_may_import(
            path,
            skill.signature_reason,
            self._approval_store,
            snapshot,
        )
        skill.owner_vouched = bool(external_import_allowed)
        skill.view_files = _view_files(snapshot)
        if py_exists and ((require_signed and not skill.trusted) or not external_import_allowed):
            # Strict mode: refuse to exec untrusted code in-process. The skill is
            # flagged sandboxed; the HUD/executor can run it via the Sandbox.
            skill.sandboxed = True
            if not external_import_allowed:
                logger.warning(
                    "External skill '%s' is %s without owner approval — module NOT "
                    "loaded in-process (flagged sandboxed)",
                    name,
                    skill.signature_reason,
                )
            else:
                logger.warning(
                    "Skill '%s' is %s and JARVIS_REQUIRE_SIGNED_SKILLS=1 — module NOT "
                    "loaded in-process (flagged sandboxed)",
                    name,
                    skill.signature_reason,
                )
        elif py_exists:
            if not skill.trusted:
                logger.info(
                    "Skill '%s' is %s — loaded in advisory mode (flagged untrusted)",
                    name,
                    skill.signature_reason,
                )
            try:
                module_name = f"skill_{name}"
                snapshot_holder, snapshot_root = _materialize_source_snapshot(snapshot)
                snapshot_py_file = snapshot_root / "main.py"
                source_loader = _SourceOnlyLoader(module_name, str(snapshot_py_file))
                spec = importlib.util.spec_from_file_location(
                    module_name,
                    snapshot_py_file,
                    loader=source_loader,
                )
                if not spec or not spec.loader:
                    raise ImportError(f"no snapshot loader for skill module: {name}")
                mod = importlib.util.module_from_spec(spec)
                mod.__skill_snapshot__ = snapshot_holder
                spec.loader.exec_module(mod)
                skill.module = mod
                if hasattr(mod, "register"):
                    mod.register(skill)
                if hasattr(mod, "get_commands"):
                    for cmd in mod.get_commands():
                        skill.register_command(cmd, getattr(mod, cmd))
                logger.info(f"Loaded skill module: {name}")
            except Exception as e:
                if external:
                    skill.sandboxed = True
                logger.warning(f"Failed to load skill module {name}: {e}")

        self._register(name, skill)
        logger.info(f"Loaded skill: {name} v{skill.version}")

    def _parse_manifest(
        self,
        path: Path,
        *,
        source_bytes: bytes | None = None,
    ) -> dict:
        # utf-8-sig: a byte-order mark from a Windows editor must not defeat the
        # ``---`` fence check or the heading dialect's ``# name`` line (H327).
        content = (
            source_bytes.decode("utf-8-sig")
            if source_bytes is not None
            else path.read_text(encoding="utf-8-sig")
        )
        default_name = path.parent.name

        # SKILL.md comes in two dialects: our own Markdown-heading style
        # (# name / > desc / **Version:** …) and the agentskills.io / Hermes
        # YAML-frontmatter style (--- … ---). Detect frontmatter first; fall
        # back to the heading parser for everything else.
        fm, body = _split_frontmatter(content)
        if fm is not None:
            try:
                return self._manifest_from_frontmatter(fm, body, default_name)
            except Exception:
                # Third-party frontmatter the normaliser cannot read registers the skill
                # under its directory name instead of failing its whole discovery.
                logger.warning("Skill frontmatter in %s could not be read; using defaults", path, exc_info=True)
                return self._manifest_from_headings("", default_name)
        return self._manifest_from_headings(content, default_name)

    def _manifest_from_frontmatter(self, fm: dict, body: str, default_name: str) -> dict:
        meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
        hermes = meta.get("hermes") if isinstance(meta.get("hermes"), dict) else {}

        # A YAML list, "[a, b]" or "a, b" alike (the key:value fallback leaves a flow
        # list as a string), as plain strings: a YAML date in `agents:` must not reach
        # a JSON route as a date object.
        requires = _fm.str_list(fm.get("requires")) or _fm.str_list(hermes.get("requires_toolsets"))
        agents = _fm.str_list(fm.get("agents"))
        commands = self._normalize_commands(fm.get("commands"))
        if not commands:
            commands = self._parse_commands_from_body(body)

        manifest = {
            # agentskills.io caps: a name at 64 characters, a description at 1024.
            "name": _fm.text(fm.get("name"), limit=_fm.MAX_NAME_LENGTH) or default_name,
            # No declared description: the first body line, as Hermes' listing reads it.
            "description": _fm.cap_description(fm.get("description"))
            or _fm.cap_description(_fm.first_body_line(body)),
            "version": _fm.text(fm.get("version")) or "0.1.0",
            "author": _fm.joined(fm.get("author")) or "unknown",
            "license": _fm.joined(fm.get("license")),
            "agents": agents,
            "requires": requires,
            "commands": commands,
        }
        # H327 — every other key Hermes recognises, normalised (metadata only).
        manifest.update(_fm.contract_fields(fm))
        return manifest

    def _manifest_from_headings(self, content: str, default_name: str) -> dict:
        manifest = {
            "name": default_name,
            "description": "",
            "version": "0.1.0",
            "agents": [],
            "requires": [],
            "commands": [],
        }

        in_commands = False

        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("# "):
                manifest["name"] = _fm.heading_name(stripped) or manifest["name"]   # the last one wins
                in_commands = False
            elif stripped.startswith("> "):
                manifest["description"] = stripped[2:].strip()
            elif stripped.startswith("**Version:**"):
                manifest["version"] = stripped.split("**Version:**")[1].strip()
            elif stripped.startswith("**Author:**"):
                manifest["author"] = stripped.split("**Author:**")[1].strip()
            elif stripped.startswith("**Agents:**"):
                agents_str = stripped.split("**Agents:**")[1].strip()
                manifest["agents"] = [a.strip() for a in agents_str.split(",")]
            elif stripped.startswith("**Requires:**"):
                req_str = stripped.split("**Requires:**")[1].strip()
                manifest["requires"] = [r.strip() for r in req_str.split(",")]
            elif stripped.startswith("## Commands"):
                in_commands = True
            elif in_commands and stripped.startswith("- `"):
                match = re.match(r"- `(\w+)(?:\s+<([^>]+)>)?`\s*—\s*(.+)", stripped)
                if match:
                    manifest["commands"].append(
                        {
                            "command": match.group(1),
                            "args": match.group(2) or "",
                            "description": match.group(3),
                        }
                    )

        return manifest

    @staticmethod
    def _normalize_commands(raw) -> list[dict]:
        """Coerce a frontmatter ``commands`` value into safe command dicts.

        Remote/imported SKILL.md frontmatter is written verbatim, so entries may
        be bare strings or carry regex metacharacters. Keep only a ``\\w+`` command
        token (matched whole in parse_command) — anything else is dropped rather
        than allowed to crash parse_command on every subsequent chat turn.
        """
        out: list[dict] = []
        if not isinstance(raw, list):
            return out
        for entry in raw[: 4 * _fm.MAX_LIST_ITEMS]:
            if isinstance(entry, dict):
                cmd = entry.get("command")
                if isinstance(cmd, str) and re.fullmatch(r"\w+", cmd):
                    # The rest of the entry is third-party YAML too: plain, finite
                    # JSON types only (H327), with the command token kept whole.
                    safe = _fm.json_safe(entry) or {}
                    safe["command"] = cmd
                    out.append(safe)
            elif isinstance(entry, str) and re.fullmatch(r"\w+", entry):
                out.append({"command": entry})
        return out

    @staticmethod
    def _parse_commands_from_body(body: str) -> list[dict]:
        commands: list[dict] = []
        in_commands = False
        for line in body.split("\n"):
            stripped = line.strip()
            if stripped.startswith("## "):
                in_commands = stripped[3:].strip().lower().startswith("commands")
            elif in_commands and stripped.startswith("- `"):
                match = re.match(r"- `(\w+)(?:\s+<([^>]+)>)?`\s*—\s*(.+)", stripped)
                if match:
                    commands.append(
                        {
                            "command": match.group(1),
                            "args": match.group(2) or "",
                            "description": match.group(3),
                        }
                    )
        return commands

    def parse_command(self, text: str) -> Optional[tuple[str, str, str]]:
        """Parse text for skill commands like 'weather bucuresti' or 'skill:weather bucuresti'.

        A bare command word is matched only against skills that run on this host (H328),
        so one for another OS never takes a word a supported skill also declares; named
        as ``skill:<name>``, it is still found, and ``Skill.execute`` says why it refuses."""
        from .visibility import host_platforms, readiness

        text = text.strip().lower()

        skill_match = re.match(r"skill:(\w+)\s+(.+)$", text)
        if skill_match:
            return (skill_match.group(1), skill_match.group(1), skill_match.group(2))

        host = host_platforms()
        runnable = [(name, skill) for name, skill in self.skills.items()
                    if readiness(skill, host=host)[0] == "ready"]
        for name, skill in runnable:
            for cmd_meta in skill.commands_meta:
                cmd_name = cmd_meta.get("command") if isinstance(cmd_meta, dict) else None
                if not isinstance(cmd_name, str) or not cmd_name:
                    continue
                pattern = rf"^{re.escape(cmd_name)}\s+(.+)$"
                match = re.match(pattern, text)
                if match:
                    return (name, cmd_name, match.group(1))

        for name, skill in runnable:
            for cmd_meta in skill.commands_meta:
                cmd_name = cmd_meta.get("command") if isinstance(cmd_meta, dict) else None
                if not isinstance(cmd_name, str) or not cmd_name:
                    continue
                if text.strip() == cmd_name:
                    return (name, cmd_name, "")

        return None

    def generate_skill(self, *args, **kwargs) -> Optional[str]:
        """Generate a new skill (see :meth:`_generate_skill`). A generation that fails after
        its usage row was written puts the sidecar back as it was: no stray agent row."""
        self._creation_undo = None
        try:
            return self._generate_skill(*args, **kwargs)
        except Exception:
            undo, self._creation_undo = self._creation_undo, None
            put_back = getattr(self._usage, "put_back", None)
            if undo is not None and callable(put_back):
                try:
                    put_back(undo)
                except Exception:
                    logger.warning("the usage row of a skill that was not generated could not be removed",
                                   exc_info=True)
            raise

    def _generate_skill(
        self,
        agent_id: str,
        task_description: str,
        solution_steps: list[str],
        command_name: str = None,
        output: str = None,
        write_origin: str = "learning",
    ) -> Optional[str]:
        """
        Generate a new skill from a successful agent task completion.
        Writes SKILL.md + main.py template to skills/<name>/.
        Returns the skill name if created, None if skipped.
        """
        # This call's own outcome only: a refusal or skip before the checks below must not
        # report an earlier generation's problems or warnings, perhaps another
        # conversation's (review-H350 F4, review-H507 F3).
        self.last_generation_problems = []
        self.last_generation_warnings = []
        skill_name = self._name_from_task(task_description)
        # Generated skills are personal content — they land in the user data
        # home when one is active (falling back to the bundled tree in dev).
        skill_dir = _writable_skills_dir() / skill_name
        if skill_dir.exists() or (SKILLS_DIR / skill_name).exists():
            logger.info(f"Skill '{skill_name}' already exists, skipping generation")
            return None
        cmd = command_name or skill_name

        if not _skill_generation_allowed(
            {
                "kind": SKILL_GENERATION_CONTRACT_KIND,
                "action": "generate",
                "agent": agent_id,
                "name": skill_name,
                "command_name": cmd,
                "steps_count": len(solution_steps or []),
                "has_output": bool(output),
            }
        ):
            return None

        # CDX-8: the [learn:…] task/steps/command are UNTRUSTED LLM output (an injected
        # response could mint an attacker-named, attacker-described skill). Scan before we
        # create anything; never write injection-flagged content to disk as a skill.
        from ..security import quarantine

        flags = quarantine.detect_injection(" ".join([task_description, *solution_steps, str(cmd)]))
        if flags:
            logger.warning(
                "Skill generation blocked — injection-flagged content from %s: %s", agent_id, flags
            )
            return None

        # The scanner above has now seen the raw command name; from here on the value is
        # written to disk (as a `def` and as a SKILL.md command token), so it must be a
        # bare identifier.
        cmd = _safe_command_name(cmd, skill_name)

        steps_text = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(solution_steps))

        skill_md = f"""# {skill_name.replace("_", " ").title()}

> {task_description}

**Version:** 0.1.0
**Author:** jarvis-agent:{agent_id}
**Agents:** {agent_id}
**Requires:**

{task_description}

## Usage
Agent-generated skill from successful task completion.

## Commands
- `{cmd} <input>` — {task_description}

## Steps
{steps_text}
"""
        if output:
            skill_md += f"\n## Example Output\n```\n{output}\n```\n"

        # H350 — the generated document passes the same check as any other write, before
        # its folder exists: a description past 1,024 characters, a second '# ' line from
        # the task text, and the like, are refused with the field and the reason.
        from .validate import validate_skill_md

        self.last_generation_problems = validate_skill_md(skill_md)
        if self.last_generation_problems:
            logger.warning("Skill generation refused: %s",
                           "; ".join(str(p) for p in self.last_generation_problems))
            return None
        # H330 — writing a skill folder crosses the skill.generation kernel gate before it
        # exists (a halt or the autonomy policy stops it); the CDX-8 quarantine below is
        # the owner's floor, so a QUEUE proceeds to it.
        refused = self._generation_kernel_refusal(
            {"action": "generate", "agent": agent_id, "name": skill_name, "command_name": cmd,
             "quarantined": True, "risk_tier": 1, "reversible": True},
            title="Generate a skill (quarantined for review)")
        if refused:
            logger.warning("Skill generation refused by the action kernel (%s): %s", refused, skill_name)
            return None
        # H20.5 / H349 — provenance, decided now and written before the folder exists: a
        # fresh row with the sticky agent marker and who wrote the skill (``write_origin``:
        # the learning loop and the background review are curated, a skill the model wrote
        # with its tool inside a turn is not), under the name the skill will REGISTER as
        # (the manifest title, what loader.skills is keyed by — not the folder slug). So the
        # row is right whenever the skill first loads: at once, after the owner's load set
        # lets it in, or at the start after a crash. A skill whose row cannot be written is
        # not generated: it would otherwise read as nobody's, or inherit whatever an
        # earlier holder of the name left (a pin).
        title = self.manifest_name(skill_dir, skill_md)
        # Fourth review: the title is checked against every installed skill first (the
        # registry and every root, :func:`name_holder`) — the folder check above compares
        # folder names only, and a skill of this title may live in a folder of another
        # name. A held name is never generated onto, and its row is not touched.
        if title in self.skills or name_holder(title, except_dir=skill_dir, registry=self.skills) is not None:
            logger.info("A skill named %r is already installed; skipping generation", title)
            return None
        settle = getattr(self._usage, "settle_created", None)
        if callable(settle):
            try:
                self._creation_undo = settle(title, "", agent_created=True, write_origin=write_origin)
            except Exception:
                logger.warning("the usage sidecar could not record the new skill %r as agent-made; it is not "
                               "generated", skill_name, exc_info=True)
                return None
        skill_dir.mkdir(parents=True, exist_ok=True)
        # The bytes checked, never text mode: Windows would write every '\n' as '\r\n'.
        (skill_dir / "SKILL.md").write_bytes(skill_md.encode("utf-8"))

        # The shape below is the loader's contract, not decoration:
        #   * a command function takes (args, context=None) — Skill.execute() dispatches
        #     `cmd_fn(args, context)` or `cmd_fn(args)`, never (cmd, args, context);
        #   * every get_commands() name must exist module-level — _load_skill() resolves
        #     it with getattr(mod, name);
        #   * handle() stays the 3-arg module-level fallback for unregistered commands.
        # This matches every hand-written skill (see skills/pm/main.py).
        main_py = '''"""
$skill_name.py — Auto-generated skill from $agent_id
Generated: $timestamp

Implement the real logic in $cmd(). Command functions take (args, context=None);
handle() is the module-level fallback for commands that aren't registered.
"""

import logging

logger = logging.getLogger("jarvis.skills.$skill_name")


async def $cmd(args: str, context: dict | None = None) -> str:
    """`$cmd <input>` — implement the real logic here."""
    logger.info("Skill $skill_name.$cmd called with args: %s", args)
    return "[skill:$skill_name] executed — implement logic in $cmd()"


def get_commands() -> list[str]:
    return ["$cmd"]


async def handle(cmd: str, args: str, context: dict | None = None) -> str:
    """Module-level fallback for commands the loader did not register."""
    if cmd == "$cmd":
        return await $cmd(args, context)
    return f"[skill:$skill_name] unknown command: {cmd}"


def register(skill):
    """Register commands with the skill system."""
    skill.register_command("$cmd", $cmd)
'''
        main_py = (
            main_py.replace("$skill_name", skill_name)
            .replace("$agent_id", agent_id)
            .replace("$cmd", cmd)
            .replace("$timestamp", datetime.now(timezone.utc).isoformat())
        )
        (skill_dir / "main.py").write_text(main_py, encoding="utf-8")

        # CDX-8: quarantine by default. An agent-emitted [learn:…] is untrusted LLM output
        # that becomes executable code — strictly more dangerous than a downloaded skill, so
        # it must not be MORE trusted than one. Do NOT self-sign and do NOT exec it
        # in-process; mint it PENDING_REVIEW. `_load_skill` registers it (so it's visible for
        # review) but never runs its module until `approve_generated_skill()` (owner-gated)
        # signs + activates it. Auto-generation stays on; only promotion-to-reusable is gated.
        (skill_dir / "PENDING_REVIEW").write_text(
            f"agent={agent_id}\ntask={task_description}\n"
            f"generated={datetime.now(timezone.utc).isoformat()}\n",
            encoding="utf-8",
        )
        self._load_skill(skill_dir)
        from ..code_guidance import scan_tree

        try:
            self.last_generation_warnings = scan_tree(skill_dir)
        except Exception:
            logger.warning("code guidance for a generated skill failed", exc_info=True)
            self.last_generation_warnings = []
        if self.last_generation_warnings:
            logger.warning("Generated skill '%s' has %d code warning(s): %s", skill_name,
                           len(self.last_generation_warnings),
                           ", ".join(sorted({w["rule"] for w in self.last_generation_warnings})))
        logger.info(
            "Generated skill '%s' from %s — quarantined PENDING REVIEW (not active)",
            skill_name,
            agent_id,
        )
        return skill_name

    def approve_generated_skill(self, name: str, expected_fingerprint: str | None = None) -> bool:
        """Persist an owner approval outside the skill tree, then activate it.

        Pending generated skills and quarantined legacy approvals are eligible.
        The legacy in-tree marker can identify a re-approval candidate but never
        authorizes import by itself.
        """
        self.last_approval_refusal = ""
        # Resolve to the skill dir: accept the registry name (manifest title, what the
        # pending-list endpoint exposes) OR the on-disk dir slug.
        reg = self.skills.get(name)
        if reg is not None and getattr(reg, "path", None):
            skill_dir = Path(reg.path)
        else:
            # Pending skills may live in either root (generated ones go to the
            # user data home when active) — resolve to whichever holds the marker.
            user_dir = _user_skills_dir()
            candidates = [SKILLS_DIR / name] + ([user_dir / name] if user_dir else [])
            skill_dir = next(
                (c for c in candidates if (c / "PENDING_REVIEW").exists()), candidates[0]
            )
        pending_marker = skill_dir / "PENDING_REVIEW"
        legacy_marker = skill_dir / OWNER_APPROVED_MARKER
        registered = next(
            (
                skill
                for skill in self.skills.values()
                if Path(getattr(skill, "path", "")).resolve() == skill_dir.resolve()
            ),
            None,
        )
        legacy_reapproval = bool(
            legacy_marker.exists()
            and registered is not None
            and registered.sandboxed
            and _is_external_skill(skill_dir)
        )
        if not pending_marker.exists() and not legacy_reapproval:
            return False
        if not isinstance(expected_fingerprint, str) or not expected_fingerprint.startswith("sha256:"):
            self.last_approval_refusal = "review_fingerprint_required"
            return False
        try:
            reviewed_snapshot = signing.source_snapshot(skill_dir)
        except OSError:
            self.last_approval_refusal = "reviewed_source_unavailable"
            return False
        if reviewed_snapshot.fingerprint != expected_fingerprint:
            self.last_approval_refusal = "reviewed_source_changed"
            return False
        if not _skill_generation_allowed(
            {
                "kind": SKILL_GENERATION_CONTRACT_KIND,
                "action": "approve",
                "agent": "owner",
                "name": skill_dir.name,
                "command_name": name,
            }
        ):
            return False
        # H330 — promoting LLM-authored code to executable is the most privileged skill
        # action: it crosses the skill.generation kernel gate (on top of admin_guard and
        # the contract) before anything is signed. A DENY or a failing gate leaves the skill
        # quarantined; a QUEUE is this owner's own decision.
        refused = self._generation_kernel_refusal(
            {"action": "approve", "agent": "owner", "name": skill_dir.name, "command_name": name,
             "requested_by": "owner", "risk_tier": 3, "reversible": True, "approval_mode": "owner"},
            title="Approve a generated skill (make it executable)")
        if refused:
            self.last_approval_refusal = refused
            logger.warning("Generated skill '%s' not approved: the action kernel said %s", name, refused)
            return False
        try:
            current = signing.source_snapshot(skill_dir)
            if current.fingerprint != expected_fingerprint:
                self.last_approval_refusal = "reviewed_source_changed"
                return False
            signing.sign_skill(skill_dir, snapshot=current)
            if signing.source_snapshot(skill_dir).fingerprint != expected_fingerprint:
                self.last_approval_refusal = "reviewed_source_changed"
                return False
            self._approval_store.approve(skill_dir, snapshot=current)
        except OSError:
            self.last_approval_refusal = "reviewed_source_unavailable"
            return False
        legacy_marker.unlink(missing_ok=True)
        pending_marker.unlink(missing_ok=True)
        self._load_skill(skill_dir)
        if safe_mode.enabled():
            # H275: _load_skill left it out, since it did not ship; it loads on a normal boot.
            logger.info("Generated skill '%s' approved; it loads on the next normal boot (safe mode)", name)
        else:
            logger.info("Generated skill '%s' approved + activated", name)
        return True

    # ── H331: the owner reads a quarantined skill whole, and can discard it ──────────

    #: Bounds on one review answer: files listed, characters shown per file and in all.
    REVIEW_MAX_FILES = 50
    REVIEW_FILE_CHARS = 64 * 1024
    REVIEW_TOTAL_CHARS = 512 * 1024

    def _pending_skill_dir(self, name: str) -> Optional[Path]:
        """The folder of the quarantined skill ``name`` (its registry name or its on-disk
        slug), or None when no such skill awaits review. Only a real folder directly under
        a discovery root (the shipped tree or the owner's) holding a plain ``PENDING_REVIEW``
        qualifies, so neither a crafted name nor a symlink reaches outside the skills trees."""
        name = str(name or "")
        if not name or name in {".", ".."} or any(c in name for c in ("/", "\\", "\x00")):
            return None
        user_dir = _user_skills_dir()
        roots = [SKILLS_DIR] + ([user_dir] if user_dir else [])
        candidates: list[Path] = []
        reg = self.skills.get(name)
        if reg is not None and getattr(reg, "path", None):
            candidates.append(Path(reg.path))
        candidates += [root / name for root in roots]
        for skill_dir in candidates:
            try:
                if skill_dir.is_symlink() or not skill_dir.is_dir():
                    continue
                marker = skill_dir / "PENDING_REVIEW"
                if marker.is_symlink() or not marker.is_file():
                    continue
                parent = skill_dir.resolve().parent
                if any(parent == root.resolve() for root in roots):
                    return skill_dir
            except OSError:
                continue
        return None

    def pending_skill_detail(self, name: str) -> Optional[dict]:
        """Everything a quarantined skill would run, as the owner reviews it before approval
        (H331): every file of its folder with its text (SKILL.md first, then the code and
        the rest), the quarantine note (who generated it, from which task) and the
        code-guidance findings. Bounded per file and in all; a file cut short, binary, a
        link or left out says so. None when ``name`` awaits no review."""
        skill_dir = self._pending_skill_dir(name)
        if skill_dir is None:
            return None
        try:
            snapshot = signing.source_snapshot(skill_dir)
        except OSError:
            snapshot = None
        captured = {item.relative_path: item.content for item in snapshot.files} if snapshot else {}
        paths = ([skill_dir / rel for rel in sorted(captured)] if snapshot is not None
                 else sorted(skill_dir.rglob("*")))
        files: list[dict] = []
        shown = 0
        more = 0
        for path in paths:
            rel = path.relative_to(skill_dir).as_posix()
            if rel == "PENDING_REVIEW" or (path.is_dir() and not path.is_symlink()):
                continue
            if len(files) >= self.REVIEW_MAX_FILES:
                more += 1
                continue
            entry: dict = {"path": rel, "text": None}
            if path.is_symlink():
                entry["symlink"] = True
                files.append(entry)
                continue
            if snapshot is not None:
                raw = captured[rel]
            else:
                try:
                    raw = path.read_bytes()
                except OSError:
                    entry["unreadable"] = True
                    files.append(entry)
                    continue
            entry["size"] = len(raw)
            entry["sha256"] = hashlib.sha256(raw).hexdigest()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                entry["binary"] = True
                files.append(entry)
                continue
            room = max(0, min(self.REVIEW_FILE_CHARS, self.REVIEW_TOTAL_CHARS - shown))
            entry["text"] = text[:room]
            entry["truncated"] = len(text) > room
            shown += len(entry["text"])
            files.append(entry)
        files.sort(key=lambda f: (f["path"] != "SKILL.md", f["path"]))
        try:
            note = (skill_dir / "PENDING_REVIEW").read_text(encoding="utf-8", errors="replace")[:4096]
        except OSError:
            note = ""
        from ..code_guidance import scan_tree

        try:
            warnings = scan_tree(skill_dir)
        except Exception:
            logger.warning("code guidance for pending skill %s failed", skill_dir.name, exc_info=True)
            warnings = []
        registered = next((n for n, s in self.skills.items() if Path(getattr(s, "path", "")) == skill_dir), None)
        skill = self.skills.get(registered) if registered else None
        return {
            "name": registered or skill_dir.name,
            "folder": skill_dir.name,
            "description": str(getattr(skill, "description", "") or "") if skill is not None else "",
            "agents": list(getattr(skill, "agents", []) or []) if skill is not None else [],
            "review_note": note,
            "files": files,
            "more_files": more,
            "warnings": warnings,
            "fingerprint": snapshot.fingerprint if snapshot is not None else None,
        }

    def pending_skill_fingerprint(self, name: str) -> str | None:
        """Current stable source identity of one still-quarantined skill."""
        skill_dir = self._pending_skill_dir(name)
        if skill_dir is None:
            return None
        try:
            return signing.source_snapshot(skill_dir).fingerprint
        except OSError:
            return None

    def discard_generated_skill(self, name: str, archive_dir: Path) -> Optional[Path]:
        """Reject a quarantined skill (H331): its folder leaves the skills tree for
        ``archive_dir`` (kept outside every discovery root, so it never loads again while
        the owner can still read what was refused); its registry entry and any approval
        bound to its path go. Only a skill that awaits review is discarded — an approved or
        shipped one is never touched. Returns where the folder went, or None."""
        import shutil

        skill_dir = self._pending_skill_dir(name)
        if skill_dir is None:
            return None
        archive = Path(archive_dir)
        archive.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        dest = archive / f"{skill_dir.name}-{stamp}"
        suffix = 1
        while dest.exists():
            suffix += 1
            dest = archive / f"{skill_dir.name}-{stamp}-{suffix}"
        shutil.move(str(skill_dir), str(dest))
        for key in [k for k, s in list(self.skills.items()) if Path(getattr(s, "path", "")) == skill_dir]:
            del self.skills[key]
            # H349: rejected for good (the discard archive is never loaded again), pinned or
            # not: its sidecar row goes with it — unless another installed folder still
            # holds the name, whose row it then is.
            self.forget_removed(key)
        self.revoke_approval(skill_dir)
        logger.info("Pending skill '%s' discarded by the owner (archived to %s)", skill_dir.name, dest)
        return dest

    def sign_skill(self, name: str) -> Optional[str]:
        """Sign an already-discovered skill in place; re-verify it. (H12.1)"""
        skill = self.skills.get(name)
        if skill is None:
            return None
        line = signing.sign_skill(skill.path)
        # Load it again, so its trust, its vouch and what skill_view serves all describe
        # the bytes just signed, not the ones seen at start (review-H318 n-1).
        self._load_skill(Path(skill.path), discovery_root=Path(skill.path).parent)
        return line

    def owner_standing(self, skill: "Skill") -> dict:
        """What vouches for ``skill``'s bytes as they are on disk now (review-H318b M-1).

        ``bundled``: it ships with Nerva, by its load or by where it lives (review-H318c
        n-6: a shipped skill whose bytes drifted loads as external, yet is product source).
        ``signed``: its SKILL.sig verifies. ``approved``: the owner approved these exact
        bytes. ``key_missing``: a keyed SKILL.sig the missing key cannot renew. ``snapshot``:
        the one read of the tree all of these judged, which a renewal must match (m-1)."""
        path = Path(skill.path)
        unreadable = False
        try:
            snapshot = signing.source_snapshot(path)
            _, reason = signing.verify_skill(path, snapshot=snapshot)
        except ValueError:                            # a SKILL.sig that is not UTF-8
            snapshot, reason = None, "unreadable"
        except OSError:
            # Could not read, which is not "unsigned": a sharing violation or an EIO for a
            # moment would otherwise void both vouches over an applied change
            # (review-H318g m-1). The caller retries.
            snapshot, reason, unreadable = None, "unreadable", True
        approved = (snapshot is not None
                    and self._approval_store.approved_snapshot(path, snapshot=snapshot) is not None)
        return {
            "unreadable": unreadable,
            "bundled": not getattr(skill, "external", True) or _shipped_location(path),
            "signed": reason in ("signed", "integrity-only"),
            "approved": approved,
            "key_missing": reason == "algo-mismatch" and signing._signing_key() is None,
            "snapshot": snapshot,
        }

    def restore_standing(self, path: Path, standing: dict, snapshot=None) -> None:
        """Give an approved patch's bytes the standing the replaced bytes had: re-sign what
        verified and re-approve what the owner had approved, over ``snapshot`` (the bytes
        the caller checked) when given. The owner approved this change, and only SKILL.md
        changed; a skill nothing vouched for gains no vouch."""
        if standing.get("signed"):
            signing.sign_skill(path, snapshot=snapshot)
        if standing.get("approved"):
            self._approval_store.approve(path, snapshot=snapshot)

    def manifest_name(self, path: Path, text: str) -> str:
        """The registry name a SKILL.md text would give the skill at ``path``."""
        manifest = self._parse_manifest(Path(path) / "SKILL.md", source_bytes=text.encode("utf-8"))
        return str(manifest.get("name") or Path(path).name)

    def _name_from_task(self, task: str) -> str:
        words = re.sub(r"[^a-zA-Z0-9\s]", "", task).lower().split()
        important = [
            w
            for w in words
            if w not in ("the", "a", "an", "for", "to", "in", "of", "and", "is", "at")
        ]
        if not important:
            important = ["custom"]
        # At most 48 characters before the stamp: the name is a folder and the heading, and
        # one long word from the task once made a folder name the filesystem refused (H350).
        name = "_".join(important[:4])[:48].rstrip("_") or "custom"
        timestamp = datetime.now(timezone.utc).strftime("%H%M%S")
        return f"{name}_{timestamp}"

    def get_skill(self, name: str) -> Optional[Skill]:
        return self.skills.get(name)

    def get_skills_for_agent(self, agent_id: str) -> list[Skill]:
        return [s for s in self.skills.values() if agent_id in s.agents or "all" in s.agents]

    @staticmethod
    def catalog_gate(skill: "Skill", agent_id: Optional[str] = None, *, switches: Optional[dict] = None,
                     visibility: Optional[dict] = None) -> str:
        """Why ``skill`` is not advertised to ``agent_id`` ("" when it is): ``disabled``
        (switched off by the owner, everywhere or on this turn's channel — H329),
        ``sandboxed``, ``untrusted`` (a signature that does not verify here), ``agent``
        (declared for other agents), ``unsupported`` (another operating system — H328), or
        one of the soft H328 gates, ``environment``, ``channel`` or ``tools``, which only
        hide it from what is offered (``visibility.SOFT_GATES``). ``unsupported`` comes
        after the gates that hide a skill outright, so ``skill_view`` never tells a skill
        the caller may not see from one that does not exist. The catalog, ``skills_list``
        and ``skill_view`` share it (H318). ``switches`` is a
        ``skills.switches.state()`` and ``visibility`` a ``skills.visibility.context()``
        already read."""
        from . import switches as skill_switches
        from . import visibility as skill_visibility

        if skill_switches.off_reason(skill, current=switches):
            return "disabled"
        if skill.sandboxed:
            return "sandboxed"
        reason = str(getattr(skill, "signature_reason", "") or "")
        if not getattr(skill, "trusted", False) and reason not in CATALOG_TOLERATED_UNTRUSTED_REASONS:
            return "untrusted"
        declared = [a for a in skill.agents if isinstance(a, str) and a.strip()]
        if agent_id and declared and agent_id not in declared and "all" not in declared:
            return "agent"
        host = (visibility or {}).get("host")
        if skill_visibility.readiness(skill, host=host)[0] != "ready":
            return "unsupported"
        return skill_visibility.offer_gate(skill, skill_visibility.context() if visibility is None else visibility)

    def prompt_catalog(
        self,
        agent_id: Optional[str] = None,
        *,
        limit: int = 20,
        description_chars: int = 120,
    ) -> list[dict]:
        """Bounded, model-facing rows of the commands this loader would actually honour.

        Hermes absorption 0.2: ``Agent.build_prompt`` has rendered an "Available skills"
        block from ``context["skills"]`` since the beginning, and nothing ever set the key —
        skills were imported, signed and pinned, and invisible to the model. This is the
        producer.

        Quarantined and sandboxed skills are left out: their commands cannot run in-process,
        so advertising them would teach the model a command that refuses. A skill that
        declares agents is shown only to those agents (or to all with ``all``); one that
        declares none is general. Descriptions are one line and capped, and the whole
        catalog is capped, because every row is paid for on every turn.

        H351 — these rows are rendered VERBATIM into the system prompt by
        ``Agent.build_prompt``, and both fields of a row (``command``, which carries the
        manifest's ``args``, and ``description``) come out of a SKILL.md frontmatter that may
        have been imported from a foreign install. Write-time scanning already refuses to
        *generate* injection-flagged skills and flags imported ones, but nothing stood
        between an already-on-disk manifest and the prompt. Two gates close that, both of
        which only ever narrow the block:

        * a skill that ships a ``SKILL.sig`` which does not verify here is not named at all
          — see :data:`CATALOG_TOLERATED_UNTRUSTED_REASONS`, which also states what that
          does and does not prove (it catches corruption, not an attacker who deletes the
          sidecar along with the edit);
        * a row that tries to talk to the model is dropped, scanned with the same
          ``quarantine.detect_injection`` that fences retrieved memory — over the row as
          written *and* over each copy ``quarantine._detection_variants`` derives from it
          (invisible characters deleted, whitespace collapsed, invisible characters
          replaced by a space, and every one of those again over the NFKC fold), unioned
          rather than substituted, so the scan does not depend on which invisible
          character an attacker reached for or where it was placed.

        **What the injection gate is worth, plainly.** ``detect_injection`` is a
        ten-entry regex table of high-signal phrases. It costs a row to a description
        that says "ignore all previous instructions"; it does not cost a row to one that
        says the same thing in words the table does not list, and there is no shortage of
        those. It raises the floor on copied-in manifests and careless imports. It is not
        a filter a motivated author cannot write around, and nothing here should be read
        as though it were.

        A hit drops the one row, never the block, and every drop is logged by skill name so a
        disappearance from the model's index is never silent; if the trust gate takes every
        skill, that is logged at ERROR rather than quietly returning an empty block. The scan
        runs on the row as ``Agent.build_prompt`` will render it — ``f"{command}: {description}"``
        with both fields already TAG-stripped, one-lined and truncated — so every
        manifest-derived byte that reaches the prompt is scanned, and nothing beyond it is,
        which matters because it is paid for on every turn.

        Neither gate disables anything: a dropped skill is un-advertised, not revoked, and
        its command still runs if the model or the owner names it directly. Un-advertising
        must not become a silent capability revocation.
        """
        from ..security import quarantine
        from . import switches as skill_switches
        from . import visibility as skill_visibility

        rows: list[dict] = []
        dropped_untrusted: list[str] = []
        cap = max(0, int(limit))
        chars = max(0, int(description_chars))
        try:
            switched = skill_switches.state()   # H329: read once for the whole catalog
        except Exception:
            logger.warning("skill switches unreadable; nonessential skills hidden", exc_info=True)
            switched = {"__unavailable__": True}
        seen = skill_visibility.context()       # H328: the host, channel and offer, once
        full = False                            # every skill is still gated, and a hide logged
        for name in sorted(self.skills):
            skill = self.skills[name]
            gate = self.catalog_gate(skill, agent_id, switches=switched, visibility=seen)
            if gate in skill_visibility.SOFT_GATES or gate in skill_visibility.HARD_GATES:
                skill_visibility.note_hidden(skill, gate)
            if gate == "untrusted":
                dropped_untrusted.append(skill.name)
                logger.warning(
                    "Skill '%s' is NOT advertised to the model — signature %s",
                    skill.name,
                    str(getattr(skill, "signature_reason", "") or "") or "unknown",
                )
                continue
            if gate or full:
                continue
            for meta in skill.commands_meta:
                if not isinstance(meta, dict):
                    continue
                command = meta.get("command")
                if not isinstance(command, str) or not re.fullmatch(r"\w+", command):
                    continue
                # `\w+` bounds the character set and nothing bounds the length, and
                # `command` is the one row field that never passed through `_catalog_text`
                # — so a manifest declaring a 5,000-character command put 5,000 characters
                # into every agent's system prompt on every turn. Capped like its
                # neighbours. `\w` cannot carry a newline, so one-lining it is moot.
                command = command[:chars]
                args = meta.get("args") if isinstance(meta.get("args"), str) else ""
                description = meta.get("description")
                if not isinstance(description, str) or not description.strip():
                    description = skill.description
                # ``args`` is manifest text rendered as verbatim prompt bytes exactly like
                # ``description``, so it gets exactly the same treatment. It used to go
                # straight through with only an isinstance check: a newline inside it broke
                # the one-row-per-line format and handed a SKILL.md its own unattributed
                # line in the system prompt, and its length was unbounded while the rest of
                # the row was capped.
                args = _catalog_text(args, chars)
                description = _catalog_text(description, chars)
                rendered = f"{command} <{args}>" if args else command
                # Scan the row as ``Agent.build_prompt`` will render it, so no field can be
                # the one that is not looked at — and scan it as written AND over every
                # copy `_detection_variants` derives (see it for the full set), because
                # an invisible character inside or instead of a separator in a phrase
                # defeats `detect_injection` while reading to the model exactly like the
                # phrase that does not. Union, not substitution: the strip DELETES
                # characters, and a deletion destroys a match as easily as it reveals one
                # — "You are now<U+200B>in developer mode" matches as written and matches
                # nothing once stripped — so scanning the stripped copy *instead of* the
                # raw row was weaker on those inputs than not stripping at all. Both
                # copies are thrown away; the row emitted below is the original, so a
                # legitimate Arabic number sign in a description survives while an evasion
                # attempt does not decide the verdict.
                flags = quarantine.detect_injection_normalized(f"{rendered}: {description}")
                if flags:
                    logger.warning(
                        "Skill '%s' command '%s' is NOT advertised to the model — its "
                        "catalog row is injection-flagged: %s",
                        skill.name,
                        command,
                        quarantine.injection_flag_names(flags),
                    )
                    continue
                rows.append(
                    {
                        "skill": skill.name,
                        "command": rendered,
                        "description": description,
                    }
                )
                if len(rows) >= cap:
                    full = True
                    break
        if not rows and dropped_untrusted:
            # Over-filtering is the named risk of this gate, and an empty block is how it
            # would show up. Do NOT re-advertise them as a "floor": that would hand any
            # single-skill install a way to launder one edited manifest back into the
            # prompt. Say it loudly instead, so a key rotation is diagnosable.
            logger.error(
                "The model-facing skills catalog is EMPTY: %d skill(s) were dropped by the "
                "signature gate (%s). The model will be told of no skills at all. If this "
                "host's signing key changed, re-sign the tree; see "
                "CATALOG_TOLERATED_UNTRUSTED_REASONS.",
                len(dropped_untrusted),
                ", ".join(sorted(dropped_untrusted)),
            )
        return rows

    # ── H326: the category-grouped index, cached ────────────────────────────────

    def index_manifest(self) -> str:
        """A hash of everything about the loaded skills that the index reads: each skill's
        name, path, the SKILL.md bytes its trust checks ran on, its parsed manifest and its
        trust state. Any change to one of them is a different hash, so a cached block never
        outlives the skills it describes (Hermes validates its snapshot by a file manifest)."""
        rows = []
        for name in sorted(self.skills):
            skill = self.skills[name]
            files = getattr(skill, "view_files", None) or {}
            source = files.get("SKILL.md")
            digest = (hashlib.sha256(source).hexdigest() if isinstance(source, bytes)
                      else str(getattr(skill, "source_fingerprint", "") or ""))
            rows.append([
                name, str(getattr(skill, "path", "")), digest,
                json.dumps(getattr(skill, "manifest", {}), sort_keys=True, default=str),
                bool(getattr(skill, "trusted", False)), str(getattr(skill, "signature_reason", "") or ""),
                bool(getattr(skill, "sandboxed", False)),
            ])
        return hashlib.sha256(json.dumps([INDEX_FORMAT, rows], sort_keys=True).encode("utf-8")).hexdigest()

    @staticmethod
    def _index_key(manifest: str, agent_id: Optional[str], switched: dict, seen: dict,
                   limit: int, chars: int) -> str:
        offered = seen.get("offered_tools")
        context = {
            "channel": str(seen.get("channel") or ""),
            "environments": sorted(str(e) for e in (seen.get("environments") or ())),
            "offered_tools": None if offered is None else sorted(str(t) for t in offered),
            "host": sorted(str(h) for h in (seen.get("host") or ())),
        }
        payload = [INDEX_FORMAT, manifest, agent_id or "", switched, context, limit, chars]
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    def prompt_index(
        self,
        agent_id: Optional[str] = None,
        *,
        limit: int = 40,
        description_chars: int = 120,
    ) -> str:
        """The model-facing skills index: one row a skill (name and description, then its
        commands), grouped under its category — what Hermes' ``build_skills_system_prompt``
        renders, where ``prompt_catalog`` gives flat command rows.

        It shows what ``prompt_catalog`` and ``skills_list`` would: the same
        :meth:`catalog_gate` (switched off, sandboxed, a signature that fails here, another
        agent's skill, another OS, a soft H328 gate), and a row whose text — category,
        name, description and commands, as rendered — is injection-flagged is dropped, as
        the catalog drops it. A skill with no command is listed too: its instructions are
        what ``skill_view`` reads.

        Cached (H326): a block is kept in an in-process LRU of :data:`INDEX_LRU_SIZE` and
        in a disk snapshot, both keyed by :meth:`index_manifest` and everything else the
        gates read (the agent, the switches, the turn's channel, environments, offered
        tools and host, the bounds). A snapshot is used only when its manifest hash is
        this loader's, its text is scanned again, and every row in it is one this loader
        would write now for a skill the gates show (:meth:`_index_rows_current`); the
        manifest hash is not a secret, so a block failing either check is rebuilt. A cache
        hit skips the per-skill hide notes; the first build of each key logs them.

        H389: under the coding posture (the turn's offer, ``visibility.coding_posture`` —
        Hermes ``agent.coding_context: focus``) a non-coding category
        (``visibility.NON_CODING_CATEGORIES``) is one line of its skills' names, and a note
        closing the index says why; names are never hidden. The posture is read off the
        offered tools, which the cache key already holds."""
        from . import switches as skill_switches
        from . import visibility as skill_visibility

        cap = max(0, int(limit))
        chars = max(0, int(description_chars))
        try:
            switched = skill_switches.state()
        except Exception:
            logger.warning("skill switches unreadable; nonessential skills hidden", exc_info=True)
            switched = {"__unavailable__": True}
        seen = skill_visibility.context()
        manifest = self.index_manifest()
        key = self._index_key(manifest, agent_id, switched, seen, cap, chars)
        with _INDEX_LOCK:
            cached = _INDEX_LRU.get(key)
            if cached is not None:
                _INDEX_LRU.move_to_end(key)
                return cached
        text = self._read_index_snapshot(manifest, key)
        if text is not None:
            try:
                current = self._index_rows_current(text, agent_id, switched=switched, seen=seen,
                                                   limit=cap, chars=chars)
            except Exception:
                current = False
            if not current:
                logger.warning("skills index snapshot holds rows this loader would not write; rebuilt")
                text = None
        if text is None:
            text = self._build_prompt_index(agent_id, switched=switched, seen=seen, limit=cap, chars=chars)
            self._write_index_snapshot(manifest, key, text)
        with _INDEX_LOCK:
            _INDEX_LRU[key] = text
            _INDEX_LRU.move_to_end(key)
            while len(_INDEX_LRU) > INDEX_LRU_SIZE:
                _INDEX_LRU.popitem(last=False)
        return text

    def _build_prompt_index(self, agent_id: Optional[str], *, switched: dict, seen: dict,
                            limit: int, chars: int) -> str:
        from ..security import quarantine
        from . import visibility as skill_visibility

        grouped: dict[str, list[tuple[str, str]]] = {}
        shown = 0
        for name in sorted(self.skills):
            if shown >= limit:
                break
            skill = self.skills[name]
            gate = self.catalog_gate(skill, agent_id, switches=switched, visibility=seen)
            if gate in skill_visibility.SOFT_GATES or gate in skill_visibility.HARD_GATES:
                skill_visibility.note_hidden(skill, gate)
            if gate:
                continue
            label = _catalog_text(skill.name, 64)
            category, row = self._index_row(skill, chars)
            flags = quarantine.detect_injection_normalized(f"{category}: {row}")
            if not label or flags:
                logger.warning("Skill '%s' is NOT in the model's skills index — its row is "
                               "injection-flagged: %s", skill.name, quarantine.injection_flag_names(flags))
                continue
            grouped.setdefault(category, []).append((label, row))
            shown += 1
        if not grouped:
            return ""
        demoted = self._index_demoted(seen)
        lines, names_only = [INDEX_HEADER], False
        for category in sorted(grouped):
            if demoted is not None and skill_visibility.names_only_category(category):
                names = sorted({label for label, _row in grouped[category]})
                lines.append(f"  {category}{INDEX_NAMES_ONLY}{', '.join(names)}")
                names_only = True
                continue
            lines.append(f"  {category}:")
            lines.extend(f"    - {row}" for _label, row in grouped[category])
        if names_only and demoted is not None:
            lines.append(demoted)
        return "\n".join(lines)

    @staticmethod
    def _index_demoted(seen: dict) -> Optional[str]:
        """H389 — under the coding posture (the turn's offer, ``visibility.coding_posture``),
        the note that ends an index with names-only categories; None in the general posture."""
        from . import visibility as skill_visibility

        offered = seen.get("offered_tools")
        if not skill_visibility.coding_posture(offered):
            return None
        return INDEX_NAMES_ONLY_NOTES[0 if "skill_view" in offered else 1]

    @staticmethod
    def _index_row(skill: "Skill", chars: int) -> tuple[str, str]:
        """A skill's category and its index row (name, description, commands), as rendered."""
        label = _catalog_text(skill.name, 64)
        description = _catalog_text(skill.description, chars)
        commands = []
        for meta in skill.commands_meta:
            command = meta.get("command") if isinstance(meta, dict) else None
            if not isinstance(command, str) or not re.fullmatch(r"\w+", command):
                continue
            args = meta.get("args") if isinstance(meta.get("args"), str) else ""
            args = _catalog_text(args, chars)
            commands.append(f"{command[:chars]} <{args}>" if args else command[:chars])
            if len(commands) >= INDEX_MAX_COMMANDS:
                break
        row = f"{label}: {description}" if description else label
        if commands:
            row += f" (commands: {', '.join(commands)})"
        return _skill_category(skill), row

    def _index_rows_current(self, text: str, agent_id: Optional[str], *, switched: dict, seen: dict,
                            limit: int, chars: int) -> bool:
        """A snapshot block is used only if every row in it is one this loader would write
        now: a skill :meth:`catalog_gate` shows this agent in this context, under its own
        category, with its own row text, at most once, and no more rows than ``limit``. A
        block naming a hidden, switched-off or invented skill, or with an edited row, is
        rebuilt: the manifest hash it is keyed by is not a secret. (Injection flags are
        re-scanned by :meth:`_index_text_clean`.)"""
        from . import visibility as skill_visibility

        if text == "":
            return True
        by_row: dict[str, tuple[str, str]] = {}
        by_label: dict[tuple[str, str], str] = {}
        for name in sorted(self.skills):
            skill = self.skills[name]
            if self.catalog_gate(skill, agent_id, switches=switched, visibility=seen):
                continue
            category, row = self._index_row(skill, chars)
            by_row.setdefault(row, (category, name))
            by_label.setdefault((category, _catalog_text(skill.name, 64)), name)
        # H389: under the coding posture a non-coding category must be names only, under
        # the general posture none may be, and the note closes the index iff one is.
        demoted = self._index_demoted(seen)
        lines = text.split("\n")[1:]
        if demoted is not None and lines and lines[-1] == demoted:
            lines = lines[:-1]
            noted = True
        else:
            noted = False
        category, names, rows, names_only = None, set(), 0, False
        for line in lines:
            if line.startswith("    - "):
                hit = by_row.get(line[len("    - "):])
                if (hit is None or hit[0] != category or hit[1] in names
                        or (demoted is not None and skill_visibility.names_only_category(category))):
                    return False
                names.add(hit[1])
                rows += 1
                continue
            head, sep, listed = line[2:].partition(INDEX_NAMES_ONLY)
            if sep:
                if demoted is None or not skill_visibility.names_only_category(head):
                    return False
                for label in listed.split(", "):
                    hit_name = by_label.get((head, label))
                    if hit_name is None or hit_name in names:
                        return False
                    names.add(hit_name)
                    rows += 1
                names_only, category = True, None
                continue
            category = line.strip()[:-1]
        return rows <= limit and names_only == noted

    @staticmethod
    def _index_text_clean(text: object) -> bool:
        """A snapshot block is used only if it still reads as an index this build would
        write: the header, category and row lines only, and nothing injection-flagged."""
        from ..security import quarantine

        if not isinstance(text, str):
            return False
        if text == "":
            return True
        lines = text.split("\n")
        if lines[0] != INDEX_HEADER:
            return False
        if len(lines) > 1 and lines[-1] in INDEX_NAMES_ONLY_NOTES:
            lines = lines[:-1]
        for line in lines[1:]:
            if not (re.fullmatch(r"  \S[^\n]*:", line) or line.startswith("    - ")
                    or re.fullmatch(r"  \S[^\n]*" + re.escape(INDEX_NAMES_ONLY) + r"\S[^\n]*", line)):
                return False
            if quarantine.detect_injection_normalized(line):
                return False
        return True

    def _read_index_snapshot(self, manifest: str, key: str) -> Optional[str]:
        try:
            path = _index_snapshot_path()
            if not path.is_file() or path.stat().st_size > INDEX_SNAPSHOT_MAX_BYTES:
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if (not isinstance(data, dict) or data.get("format") != INDEX_FORMAT
                or data.get("manifest") != manifest or not isinstance(data.get("entries"), dict)):
            return None
        text = data["entries"].get(key)
        if text is None or not self._index_text_clean(text):
            return None
        return text

    def _write_index_snapshot(self, manifest: str, key: str, text: str) -> None:
        """Keep ``text`` in the snapshot; a write that fails costs a rebuild, never a turn."""
        try:
            path = _index_snapshot_path()
            entries: dict = {}
            try:
                if path.is_file() and path.stat().st_size <= INDEX_SNAPSHOT_MAX_BYTES:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if (isinstance(data, dict) and data.get("format") == INDEX_FORMAT
                            and data.get("manifest") == manifest and isinstance(data.get("entries"), dict)):
                        entries = {k: v for k, v in data["entries"].items()
                                   if isinstance(k, str) and isinstance(v, str)}
            except Exception:
                entries = {}
            entries.pop(key, None)
            entries[key] = text
            while len(entries) > INDEX_LRU_SIZE:
                entries.pop(next(iter(entries)))
            payload = json.dumps({"format": INDEX_FORMAT, "manifest": manifest, "entries": entries},
                                 ensure_ascii=False)
            if len(payload.encode("utf-8")) > INDEX_SNAPSHOT_MAX_BYTES:
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False,
                                             prefix=".skills_index.", suffix=".tmp") as handle:
                handle.write(payload)
                temp = Path(handle.name)
            temp.replace(path)
        except Exception:
            logger.warning("skills index snapshot could not be written", exc_info=True)
