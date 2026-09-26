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
    "calendar": {
        "SKILL.md": "fd2ad826d907a07ed9c95f837acd4072ca280c285ac90ef8ba50cc17ca9d47c1",
        "main.py": "41d0d438d27fe07b5924af212dd292be0b1d182ce4b3b0f2354a2cb34f5159f5",
    },
    "content": {
        "SKILL.md": "b59dbbacde4c197930fc94e74054dc4f3664e26c7d6e0312e1de3011e6c53969",
        "main.py": "be33a20faeaba93affa3dbc105ec05c0c7c7cc27b5a5174d9b655f87a7525bf5",
    },
    "email_triage": {
        "SKILL.md": "9b66be20f7d7fb3a3de9131185bbafe8e19d741ec9a0fb095a57fa884af4f662",
        "main.py": "84ef124d387e0af18d634866c6c13d781c143538974a0bee9105923622ced7d3",
    },
    "family_store": {
        "SKILL.md": "d61c6524741361265804b6e9393e80d99099a0fb915685343ed8f9705edc908e",
        "main.py": "95cc696e4b6be0fc2054a4b58c404b70c8bcd478cb0416e6fcb570dcf0c01e6d",
    },
    "health": {
        "SKILL.md": "9dca801816cbbbf90e33fef36a3b3cfc0a8f9e987709981bba047dc0891aaa69",
        "main.py": "e395a97304bc5720e6f757b776f39adc787a827558a23f435ce3e300d4b934a4",
    },
    "pm": {
        "SKILL.md": "b67bd2a0927713436f358baa12bce75c73ec224251c28e2931a51391e2e767a8",
        "main.py": "6bbfea103e7cfb1d43c1224e7c62febfb81fb569d77661cd370724e28d2e1dd9",
    },
    "security_monitor": {
        "SKILL.md": "959542c712e3ed1aa260870871156b692a3c9a4693decd5c95ba35665fc6dd5d",
        "main.py": "d781c8305a3307fba60de7e832e20576d55ef4ee03b5a30abd7796ab9bbbfea4",
    },
    "spotify": {
        "SKILL.md": "3c17dd7f8273f9fac8e7a3d8f19afefede4d52c9969e78f773acdd544de3b475",
        "main.py": "fb57a311f27bbf2fb1450bc9e40fcdb0d8d1d8747fb7d8f5fdf6f0530ab30e4b",
    },
    "system_monitor": {
        "SKILL.md": "42b9c0a86723a8e6eb8d867951b2732d87047706ff850286216ab91ca2e70c6c",
        "main.py": "a7b483539973c9f1ea739615b89a70242d8ff7944687f25f50b92de80f289c41",
    },
    "weather": {
        "SKILL.md": "b4fc491c3c113ae3652cf81e95ef87e80d12b20be98253ad5239e0705e8774ff",
    },
    "web_research": {
        "SKILL.md": "2893457f1840d419d0e2d57e767bedd853818d08a81e9d8177043d3109bfb737",
        "main.py": "a9f6b13997f885d2e10f9ed79150edc59d4cd8ca406b8b471f246dfccbe51737",
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
            "hermes": self.hermes_meta,
        }

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

        # H328: a skill for another operating system cannot run here, even when named.
        ready, why = readiness(self)
        if ready != "ready":
            logger.info("Skill '%s' is %s; command '%s' refused", self.name, why, command)
            return f"[skill:{self.name}] is {why}"
        if self.usage_hook is not None:
            try:
                self.usage_hook(self.name, "use")
            except Exception:
                logger.debug("usage hook failed for %s", self.name, exc_info=True)
        cmd_fn = self.commands.get(command)
        if cmd_fn:
            try:
                if context:
                    return await cmd_fn(args, context)
                return await cmd_fn(args)
            except Exception as e:
                logger.error(f"Skill {self.name} command '{command}' failed: {e}")
                return f"[skill:{self.name}] error: {e}"

        if self.module and hasattr(self.module, "handle"):
            try:
                return await self.module.handle(command, args, context or {})
            except Exception as e:
                logger.warning(
                    "Skill '%s' handle() raised for command '%s'", self.name, command, exc_info=True
                )
                return f"[skill:{self.name}] error: {e}"

        return ""


class SkillLoader:
    def __init__(self, approval_store: SkillApprovalStore | None = None):
        self.skills: dict[str, Skill] = {}
        # H350 — why the last generate_skill refused its document (empty when it did not).
        self.last_generation_problems: list = []
        # H507 — what the last generated skill's code looks like (warn-only).
        self.last_generation_warnings: list = []
        # H20.5 — optional usage-telemetry sidecar (SkillUsageStore); attached by
        # the orchestrator. None → zero behavior change.
        self._usage = None
        self._approval_store = approval_store or SkillApprovalStore()

    def attach_usage(self, store) -> None:
        """Attach a SkillUsageStore; hooks existing and future skills."""
        self._usage = store

        def _hook(name: str, kind: str) -> None:
            store.bump(name, kind)

        for skill in self.skills.values():
            skill.usage_hook = _hook

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
        roots = [SKILLS_DIR]
        # The owner's personal skills (Documents/Jarvis/skills) load AFTER the
        # bundled tree so a same-named user skill wins the registry slot.
        user_dir = _user_skills_dir()
        if (
            user_dir is not None
            and user_dir.is_dir()
            and user_dir.resolve() != SKILLS_DIR.resolve()
        ):
            if safe_mode.enabled():
                # H275: safe mode discovers the shipped skills only.
                safe_mode.note("owner_skills")
            else:
                roots.append(user_dir)
        # H285: the owner's load set, read once for this pass.
        load_set.begin("skills")
        self._load_lists = load_set.declared("skills")
        folders: set[str] = set()
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
        load_set.finish("skills", folders | set(self.skills) | set(load_set.status("skills")["skipped"]),
                        lists=self._load_lists)
        self._load_lists = None
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
            # H285: switched off by the owner's load set; nothing about it is registered.
            load_set.note_skipped("skills", name)
            return
        skill = Skill(name, path, manifest)
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
                manifest["name"] = stripped[2:].strip()
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
        """Parse text for skill commands like 'weather bucuresti' or 'skill:weather bucuresti'."""
        text = text.strip().lower()

        skill_match = re.match(r"skill:(\w+)\s+(.+)$", text)
        if skill_match:
            return (skill_match.group(1), skill_match.group(1), skill_match.group(2))

        for name, skill in self.skills.items():
            for cmd_meta in skill.commands_meta:
                cmd_name = cmd_meta.get("command") if isinstance(cmd_meta, dict) else None
                if not isinstance(cmd_name, str) or not cmd_name:
                    continue
                pattern = rf"^{re.escape(cmd_name)}\s+(.+)$"
                match = re.match(pattern, text)
                if match:
                    return (name, cmd_name, match.group(1))

        for name, skill in self.skills.items():
            for cmd_meta in skill.commands_meta:
                cmd_name = cmd_meta.get("command") if isinstance(cmd_meta, dict) else None
                if not isinstance(cmd_name, str) or not cmd_name:
                    continue
                if text.strip() == cmd_name:
                    return (name, cmd_name, "")

        return None

    def generate_skill(
        self,
        agent_id: str,
        task_description: str,
        solution_steps: list[str],
        command_name: str = None,
        output: str = None,
    ) -> Optional[str]:
        """
        Generate a new skill from a successful agent task completion.
        Writes SKILL.md + main.py template to skills/<name>/.
        Returns the skill name if created, None if skipped.
        """
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
        self.last_generation_warnings = []
        if self.last_generation_problems:
            logger.warning("Skill generation refused: %s",
                           "; ".join(str(p) for p in self.last_generation_problems))
            return None
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

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
        # H20.5 — provenance: agent-created skills are the only curatable ones.
        # Record under the REGISTERED name (the manifest title, which is what
        # loader.skills is keyed by and what the curator iterates), not the
        # on-disk slug — they differ (`# {slug.title()}` heading).
        if self._usage is not None:
            try:
                registered = next(
                    (
                        n
                        for n, s in self.skills.items()
                        if Path(getattr(s, "path", "")) == skill_dir
                    ),
                    skill_name,
                )
                self._usage.note_created(registered, "agent")
            except Exception:
                logger.debug("usage provenance note skipped", exc_info=True)
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

    def approve_generated_skill(self, name: str) -> bool:
        """Persist an owner approval outside the skill tree, then activate it.

        Pending generated skills and quarantined legacy approvals are eligible.
        The legacy in-tree marker can identify a re-approval candidate but never
        authorizes import by itself.
        """
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
        signing.sign_skill(skill_dir)
        self._approval_store.approve(skill_dir)
        legacy_marker.unlink(missing_ok=True)
        pending_marker.unlink(missing_ok=True)
        self._load_skill(skill_dir)
        logger.info("Generated skill '%s' approved + activated", name)
        return True

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
        ``unsupported`` (another operating system — H328), ``sandboxed``, ``untrusted``
        (a signature that does not verify here), ``agent`` (declared for other agents), or
        one of the soft H328 gates, ``environment``, ``channel`` or ``tools``, which only
        hide it from what is offered (``visibility.SOFT_GATES``). The catalog,
        ``skills_list`` and ``skill_view`` share it (H318). ``switches`` is a
        ``skills.switches.state()`` and ``visibility`` a ``skills.visibility.context()``
        already read."""
        from . import switches as skill_switches
        from . import visibility as skill_visibility

        if skill_switches.off_reason(skill, current=switches):
            return "disabled"
        host = (visibility or {}).get("host")
        if skill_visibility.readiness(skill, host=host)[0] != "ready":
            return "unsupported"
        if skill.sandboxed:
            return "sandboxed"
        reason = str(getattr(skill, "signature_reason", "") or "")
        if not getattr(skill, "trusted", False) and reason not in CATALOG_TOLERATED_UNTRUSTED_REASONS:
            return "untrusted"
        declared = [a for a in skill.agents if isinstance(a, str) and a.strip()]
        if agent_id and declared and agent_id not in declared and "all" not in declared:
            return "agent"
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
            logger.warning("skill switches unreadable; every skill stays on", exc_info=True)
            switched = {}
        seen = skill_visibility.context()       # H328: the host, channel and offer, once
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
            if gate:
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
                    return rows
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
