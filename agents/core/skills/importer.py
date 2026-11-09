"""
importer.py — Import skills from Hermes Agent, OpenClaw, agentskills.io.

Port of OpenJarvis's skill import system to pure Python.
Supports importing skills from:
- Hermes Agent (GitHub: NousResearch/hermes-agent)
- OpenClaw (GitHub: openclaw/skills)
- Any GitHub repo with agentskills.io-compatible manifests

Skill format: the agentskills.io / Hermes convention is a ``SKILL.md`` file
with YAML frontmatter (``name``/``description``/``version``/``author``/…) plus a
markdown instruction body, laid out as ``skills/<category>/<skill>/SKILL.md``
(category nesting is optional). Imported skills are written back out as
``SKILL.md`` so the local ``SkillLoader`` discovers them; a small
``manifest.json`` sidecar records import provenance for ``list_imported()``.
A legacy ``manifest.json``/``manifest.yaml`` layout is still accepted as a
fallback for older repos.
"""

import ctypes
import difflib
import errno
import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional

from .remote_pin import RemoteImportAuthorization, RemoteImportRefused, RemoteSkillPin

logger = logging.getLogger("jarvis.skills.importer")

# A skill slug becomes a directory name under `skills_dir`, so it is restricted to
# an identifier alphabet — the same shape the agents router uses for agent ids.
# It used to be `skill_name.lower().replace(" ", "-")`, which replaces ONLY spaces:
# path separators, "..", a leading "/" and a drive letter all survived it, and the
# result was joined straight onto skills_dir. A skill named "../../pwned" wrote to
# the grandparent directory and "/etc/jarvis-pwned" wrote at the filesystem root.
# (The route is user-guarded and DEV_MODE-only, so this is not a remote hole — but
# the name reaches the path from a remote repository listing, and a mistake or a
# hostile source should not be able to write outside the skills tree.)
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_RELEASE_TAG_RE = re.compile(r"^v[0-9]{4}\.[0-9]{1,2}\.[0-9]{1,2}(?:\.[0-9]+)?$")
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REFERENCE_PART_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

HERMES_REPO = "NousResearch/hermes-agent"
HERMES_PIN_RELEASE_TAG = "v2026.8.31"
HERMES_PIN_COMMIT = "29112bef099274229cadff79cdff7bf7b99c4b77"
HERMES_PIN_TREE = "daaffc303ae437041b7f76be17c5f61b14f2ce99"
HERMES_PIN_PATH = Path(__file__).with_name("hermes_pin_v2.json")
OPENCLAW_REPO = "openclaw/skills"
OPENCLAW_SKILLS_PATH = "main/skills"

GITHUB_RAW = "https://raw.githubusercontent.com"
GITHUB_API = "https://api.github.com"
_MAX_REMOTE_FILE_BYTES = 8 * 1024 * 1024
_MAX_REMOTE_SKILL_BYTES = 32 * 1024 * 1024


def _publish_stage_no_replace(stage: Path, target: Path) -> None:
    """Atomically publish a staged directory only if its final name is absent.

    A plain POSIX rename can replace an empty owner directory created after
    the caller's absence check. Use the platform's exclusive rename instead;
    an unsupported OS, libc, or filesystem fails closed. Stages are created in
    the destination's parent, so a successful rename keeps whole-directory
    visibility. No copy or nonexclusive rename fallback is safe here.
    """
    if os.name == "nt":
        # Python documents that os.rename on Windows always raises
        # FileExistsError when the destination exists.
        os.rename(stage, target)
        return
    if sys.platform != "darwin" and not sys.platform.startswith("linux"):
        raise OSError(errno.ENOSYS, "exclusive directory rename unavailable")

    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(stage)
    target_bytes = os.fsencode(target)
    if sys.platform == "darwin":
        # macOS SDK sys/stdio.h: RENAME_EXCL = 0x00000004; rename(2) says
        # an existing destination returns EEXIST. No AT_FDCWD is needed.
        try:
            rename_exclusive = libc.renamex_np
        except AttributeError as exc:
            raise OSError(errno.ENOSYS, "exclusive directory rename unavailable") from exc
        rename_exclusive.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename_exclusive.restype = ctypes.c_int
        result = rename_exclusive(source_bytes, target_bytes, 0x00000004)
    else:  # Linux was selected before loading libc.
        # Linux UAPI linux/fs.h: RENAME_NOREPLACE = (1 << 0);
        # linux/fcntl.h: AT_FDCWD = -100. Unsupported filesystems return
        # an error rather than falling back to a replacing rename.
        try:
            rename_exclusive = libc.renameat2
        except AttributeError as exc:
            raise OSError(errno.ENOSYS, "exclusive directory rename unavailable") from exc
        rename_exclusive.argtypes = [ctypes.c_int, ctypes.c_char_p,
                                     ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename_exclusive.restype = ctypes.c_int
        result = rename_exclusive(-100, source_bytes, -100, target_bytes, 1 << 0)
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), os.fspath(target))


def _safe_slug(skill_name: str) -> Optional[str]:
    """Directory-safe slug for *skill_name*, or None if it cannot be made safe.

    Rejects rather than sanitizes: silently rewriting "../../pwned" into "pwned"
    would import a skill under a name the caller did not ask for, which is its own
    surprise. A name that is not a plain identifier is refused.
    """
    slug = (skill_name or "").strip().lower().replace(" ", "-")
    return slug if _SLUG_RE.match(slug) else None


class SkillImportError(Exception):
    pass


@dataclass(frozen=True)
class _HermesPinEntry:
    slug: str
    path: str
    content_sha256: str
    tier: str
    files: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class _HermesPin:
    repository: str
    release_tag: str
    commit: str
    tree: str
    skills: tuple[_HermesPinEntry, ...]


def _strict_json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise SkillImportError("Hermes pin contains a duplicate JSON key")
        value[key] = item
    return value


def _require_exact_keys(value, expected: set[str], context: str) -> None:
    if type(value) is not dict or set(value) != expected:
        raise SkillImportError(f"Hermes pin {context} has an invalid schema")


def _safe_pin_path(path: str, slug: str) -> bool:
    if not isinstance(path, str) or not path or "\\" in path or len(path) > 512:
        return False
    pure = PurePosixPath(path)
    if pure.as_posix() != path:
        return False
    parts = pure.parts
    if len(parts) < 3 or parts[0] not in ("skills", "optional-skills") or parts[-1] != "SKILL.md":
        return False
    if parts[-2] != slug or any(part in ("", ".", "..") for part in parts):
        return False
    return all(_SLUG_RE.fullmatch(part) for part in parts[1:-1])


def _safe_reference_path(path: str, skill_path: str) -> bool:
    if not isinstance(path, str) or not path or "\\" in path or len(path) > 512:
        return False
    pure = PurePosixPath(path)
    if pure.as_posix() != path or any(part in ("", ".", "..") for part in pure.parts):
        return False
    prefix = skill_path.removesuffix("SKILL.md") + "references/"
    if not path.startswith(prefix) or path == skill_path:
        return False
    relative = path[len(prefix):]
    return bool(relative) and all(_REFERENCE_PART_RE.fullmatch(part) for part in PurePosixPath(relative).parts)


def _safe_hermes_category(category: str) -> bool:
    if not isinstance(category, str) or not category or "\\" in category or len(category) > 256:
        return False
    parts = category.split("/")
    return all(_safe_slug(part) == part for part in parts)


def _load_hermes_pin() -> _HermesPin:
    try:
        raw = HERMES_PIN_PATH.read_bytes()
        text = raw.decode("utf-8")
        data = json.loads(text, object_pairs_hook=_strict_json_object)
    except SkillImportError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SkillImportError("Hermes pin is unavailable or malformed") from exc

    top_keys = {
        "schema_version",
        "repository",
        "release_tag",
        "commit",
        "tree",
        "skills",
    }
    _require_exact_keys(data, top_keys, "record")
    if type(data["schema_version"]) is not int or data["schema_version"] != 2:
        raise SkillImportError("Hermes pin schema version is unsupported")
    if data["repository"] != HERMES_REPO:
        raise SkillImportError("Hermes pin repository is not the accepted upstream")
    if not isinstance(data["release_tag"], str) or not _RELEASE_TAG_RE.fullmatch(
        data["release_tag"]
    ):
        raise SkillImportError("Hermes pin release tag is not a versioned release label")
    if data["release_tag"] != HERMES_PIN_RELEASE_TAG:
        raise SkillImportError("Hermes pin release tag does not match this importer version")
    if not isinstance(data["commit"], str) or not _SHA40_RE.fullmatch(data["commit"]):
        raise SkillImportError("Hermes pin commit is not a canonical object ID")
    if data["commit"] != HERMES_PIN_COMMIT:
        raise SkillImportError("Hermes pin commit does not match this importer version")
    if not isinstance(data["tree"], str) or not _SHA40_RE.fullmatch(data["tree"]):
        raise SkillImportError("Hermes pin tree is not a canonical object ID")
    if data["tree"] != HERMES_PIN_TREE:
        raise SkillImportError("Hermes pin tree does not match this importer version")
    if type(data["skills"]) is not list or not data["skills"]:
        raise SkillImportError("Hermes pin allowlist must be non-empty")

    entries = []
    slugs: set[str] = set()
    paths: set[str] = set()
    for item in data["skills"]:
        if type(item) is not dict or set(item) not in (
            {"slug", "path", "content_sha256", "tier"},
            {"slug", "path", "content_sha256", "tier", "files"},
        ):
            raise SkillImportError("Hermes pin skill entry has an invalid schema")
        slug = item["slug"]
        path = item["path"]
        digest = item["content_sha256"]
        if not isinstance(slug, str) or _safe_slug(slug) != slug:
            raise SkillImportError("Hermes pin contains an unsafe skill slug")
        if not _safe_pin_path(path, slug):
            raise SkillImportError("Hermes pin contains an unsafe or mismatched path")
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise SkillImportError("Hermes pin contains an invalid content digest")
        tier = item["tier"]
        if tier not in ("bundled", "optional") or path.startswith("optional-skills/") != (tier == "optional"):
            raise SkillImportError("Hermes pin skill tier does not match its root")
        file_items = item.get("files", [])
        if type(file_items) is not list:
            raise SkillImportError("Hermes pin files must be a list")
        files = []
        for file_item in file_items:
            _require_exact_keys(file_item, {"path", "content_sha256"}, "reference file")
            file_path, file_digest = file_item["path"], file_item["content_sha256"]
            if not _safe_reference_path(file_path, path):
                raise SkillImportError("Hermes pin contains an unsafe reference path")
            if not isinstance(file_digest, str) or not _SHA256_RE.fullmatch(file_digest):
                raise SkillImportError("Hermes pin contains an invalid reference digest")
            if file_path in paths or file_path in (p for p, _ in files):
                raise SkillImportError("Hermes pin contains duplicate file paths")
            files.append((file_path, file_digest))
        if [p for p, _ in files] != sorted(p for p, _ in files):
            raise SkillImportError("Hermes pin reference files are not deterministic")
        if slug in slugs or path in paths:
            raise SkillImportError("Hermes pin contains duplicate skill identities")
        slugs.add(slug)
        paths.add(path)
        paths.update(p for p, _ in files)
        entries.append(_HermesPinEntry(slug=slug, path=path, content_sha256=digest,
                                       tier=tier, files=tuple(files)))

    if [entry.path for entry in entries] != sorted(entry.path for entry in entries):
        raise SkillImportError("Hermes pin skill entries are not deterministic")

    return _HermesPin(
        repository=data["repository"],
        release_tag=data["release_tag"],
        commit=data["commit"],
        tree=data["tree"],
        skills=tuple(entries),
    )


class SkillImporter:
    def __init__(self, skills_dir: str | None = None, *, resolver=None, transport_factory=None):
        if skills_dir is None:
            from .loader import _writable_skills_dir

            skills_dir = str(_writable_skills_dir())
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self._remote_resolver = resolver
        self._remote_transport_factory = transport_factory
        # H350 — why the last _save_skill refused its document (empty when it did not).
        self.last_refusal: list = []

    def _remote_client(self, authorization: RemoteImportAuthorization):
        from agents.core.http_client import RequiredEgressHTTPClient

        return RequiredEgressHTTPClient(
            plugin_name="skill-import", authorize_egress=authorization.egress_gate,
            resolver=self._remote_resolver, transport_factory=self._remote_transport_factory,
        )

    @staticmethod
    def _require_authorization(authorization: RemoteImportAuthorization | None) -> RemoteImportAuthorization:
        if not isinstance(authorization, RemoteImportAuthorization):
            raise RemoteImportRefused("authorization_unavailable")
        return authorization

    @staticmethod
    def _install_payload(source: str, slug: str, remote_pin: RemoteSkillPin,
                         *, release_tag: str | None = None, tree: str | None = None) -> dict:
        payload = {
            "kind": "skill.install", "action": "import", "name": slug,
            "source": source, "pinned": True, "requested_by": "owner",
            "risk_tier": 3, "reversible": True, "approval_mode": "owner",
            "quarantined": True, "source_repository": remote_pin.repo,
            "source_commit": remote_pin.commit, "commit": remote_pin.commit,
            "source_path": remote_pin.entry_path,
            "content_sha256": remote_pin.content_sha256,
            "files": [{"path": path, "content_sha256": digest}
                      for path, digest in remote_pin.references],
        }
        if release_tag is not None:
            payload["release_tag"] = release_tag
        if tree is not None:
            payload["tree"] = tree
        return payload

    @staticmethod
    def _check_install(authorization: RemoteImportAuthorization, payload: dict) -> str:
        try:
            verdict = authorization.install_gate(dict(payload))
        except Exception as exc:
            raise RemoteImportRefused("authorization_unavailable") from exc
        if type(verdict) is not str:
            raise RemoteImportRefused("authorization_unavailable")
        if verdict.lower() == "deny":
            raise RemoteImportRefused("install_denied")
        if verdict.lower() not in {"grant", "queue"}:
            raise RemoteImportRefused("authorization_unavailable")
        return verdict.lower()

    @staticmethod
    async def _fetch_exact_bytes(client, url: str, digest: str, *, budget: list[int]) -> bytes:
        try:
            async with client.stream("GET", url, follow_redirects=False) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    raise RemoteImportRefused("source_identity_mismatch")
                if response.status_code != 200:
                    raise RemoteImportRefused("fetch_failed")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > _MAX_REMOTE_FILE_BYTES or len(chunk) > budget[0]:
                        raise RemoteImportRefused("fetch_failed")
                    body.extend(chunk)
                    budget[0] -= len(chunk)
        except RemoteImportRefused:
            raise
        except Exception as exc:
            from agents.core.http_client import PluginEgressError

            if isinstance(exc, PluginEgressError):
                raise RemoteImportRefused("egress_denied") from exc
            raise RemoteImportRefused("fetch_failed") from exc
        raw = bytes(body)
        if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), digest):
            raise RemoteImportRefused("digest_mismatch")
        return raw

    async def import_from_hermes(
        self, skill_name: str, *, pin: _HermesPin | None = None,
        entry: _HermesPinEntry | None = None,
        authorization: RemoteImportAuthorization | None = None,
    ) -> bool:
        self.last_refusal = []
        authorization = self._require_authorization(authorization)
        skill_slug = _safe_slug(skill_name)
        if skill_slug is None:
            logger.warning("Rejected Hermes skill import: unsafe name %r", skill_name)
            return False

        if pin is None:
            pin = _load_hermes_pin()
        if entry is None:
            entry = next((item for item in pin.skills if item.slug == skill_slug), None)
        if entry is None or entry.slug != skill_slug or entry not in pin.skills:
            logger.warning("Skill '%s' is not in the Hermes pin allowlist", skill_slug)
            return False
        remote_pin = RemoteSkillPin(pin.repository, pin.commit, entry.path,
                                    entry.content_sha256, entry.files)
        payload = self._install_payload("hermes", skill_slug, remote_pin,
                                        release_tag=pin.release_tag, tree=pin.tree)
        self._check_install(authorization, payload)
        async with self._remote_client(authorization) as client:
            verified = await self._fetch_verified_hermes_skill(client, pin, entry)
        raw, text, references = verified
        self._check_install(authorization, payload)
        return await self._save_skill(
            skill_name,
            "hermes",
            skill_md_text=text,
            skill_md_bytes=raw,
            provenance=self._hermes_provenance(pin, entry),
            reference_files=references,
        )

    async def import_repo_optional(
        self, source_dir: Path, skill_name: str, expected_fingerprint: str
    ) -> bool:
        """Install a shipped optional skill only after an owner route has gated its snapshot.

        This method does no authorization itself. The caller must constrain the
        source to the product's optional allowlist and pass the fingerprint seen
        before its owner/kernel decision. New copies remain pending review even
        when the kernel grants the directory write.
        """
        from .signing import SkillSourceSnapshotError, source_snapshot
        from .validate import validate_skill_md

        slug = _safe_slug(skill_name)
        if slug is None or slug != skill_name or Path(source_dir).name != slug:
            return False
        target = self.skills_dir / slug
        if target.exists() or target.is_symlink():
            return False  # Never replace an owner copy or its approval state.
        try:
            target.resolve().relative_to(self.skills_dir.resolve())
            snapshot = source_snapshot(Path(source_dir))
        except (ValueError, OSError, SkillSourceSnapshotError):
            return False
        if snapshot.fingerprint != expected_fingerprint:
            return False
        raw = snapshot.read_bytes("SKILL.md")
        if raw is None or validate_skill_md(raw):
            return False
        stage = Path(tempfile.mkdtemp(prefix=".optional-stage-", dir=self.skills_dir))
        try:
            for item in snapshot.files:
                if item.kind != "file":
                    return False
                if "__pycache__" in Path(item.relative_path).parts:
                    continue  # Dev/test bytecode is never product skill content.
                dest = stage / item.relative_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(item.content)
            (stage / "manifest.json").write_text(json.dumps({
                "name": slug,
                "source": "nerva-optional",
                "imported": True,
                "content_sha256": hashlib.sha256(raw).hexdigest(),
                "source_fingerprint": snapshot.fingerprint,
                "source_path": f"optional-skills/{slug}/SKILL.md",
                "source_tier": "optional",
                "quarantined": True,
            }, indent=2), encoding="utf-8")
            (stage / "PENDING_REVIEW").write_text(
                f"source=nerva-optional\nsha256={hashlib.sha256(raw).hexdigest()}\n",
                encoding="utf-8",
            )
            if target.exists() or target.is_symlink():
                return False
            _publish_stage_no_replace(stage, target)
            return True
        except OSError:
            logger.warning("Could not stage optional skill '%s'", slug, exc_info=True)
            return False
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    async def import_from_openclaw(
        self, skill_name: str, *, pin: RemoteSkillPin | None = None,
        authorization: RemoteImportAuthorization | None = None,
    ) -> bool:
        return await self._import_from_github(
            OPENCLAW_REPO, skill_name, pin=pin, authorization=authorization,
            source="openclaw",
        )

    async def import_from_github(
        self, repo: str, skill_name: str, path: str = "main/skills", *,
        pin: RemoteSkillPin | None = None,
        authorization: RemoteImportAuthorization | None = None,
    ) -> bool:
        # ``path`` is retained for old Python callers, but cannot select a
        # mutable branch. The explicit pin is the only source path authority.
        return await self._import_from_github(
            repo, skill_name, pin=pin, authorization=authorization,
            source=repo.rsplit("/", 1)[-1],
        )

    @staticmethod
    async def _fetch_verified_hermes_skill(client, pin: _HermesPin, entry: _HermesPinEntry):
        paths = ((entry.path, entry.content_sha256), *entry.files)
        contents = {}
        budget = [_MAX_REMOTE_SKILL_BYTES]
        for path, expected_digest in paths:
            url = f"{GITHUB_RAW}/{pin.repository}/{pin.commit}/{path}"
            contents[path] = await SkillImporter._fetch_exact_bytes(
                client, url, expected_digest, budget=budget)
        raw = contents[entry.path]
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RemoteImportRefused("invalid_skill") from exc
        if SkillImporter._extract_frontmatter(text, strict=True).get("name") != entry.slug:
            raise RemoteImportRefused("source_identity_mismatch")
        from .validate import validate_skill_md

        if validate_skill_md(raw):
            raise RemoteImportRefused("invalid_skill")
        return raw, text, {path.removeprefix(entry.path.removesuffix("SKILL.md")): contents[path]
                           for path, _ in entry.files}

    @staticmethod
    def _hermes_provenance(pin: _HermesPin, entry: _HermesPinEntry) -> dict[str, str]:
        return {
            "source_repository": pin.repository,
            "source_release_tag": pin.release_tag,
            "source_commit": pin.commit,
            "source_tree": pin.tree,
            "source_path": entry.path,
            "content_sha256": entry.content_sha256,
            "source_tier": entry.tier,
            "source_files": [{"path": path, "content_sha256": digest}
                             for path, digest in entry.files],
        }

    async def _import_from_github(
        self, repo: str, skill_name: str, *, pin: RemoteSkillPin | None,
        authorization: RemoteImportAuthorization | None, source: str,
    ) -> bool:
        self.last_refusal = []
        if pin is None:
            raise RemoteImportRefused("missing_pin")
        if not isinstance(pin, RemoteSkillPin) or pin.repo != repo:
            raise RemoteImportRefused("invalid_pin")
        authorization = self._require_authorization(authorization)
        skill_slug = _safe_slug(skill_name)
        if skill_slug is None or pin.entry_path.rsplit("/", 2)[-2] != skill_slug:
            raise RemoteImportRefused("source_identity_mismatch")
        payload = self._install_payload(source, skill_slug, pin)
        self._check_install(authorization, payload)
        budget = [_MAX_REMOTE_SKILL_BYTES]
        async with self._remote_client(authorization) as client:
            url = f"{GITHUB_RAW}/{pin.repo}/{pin.commit}/{pin.entry_path}"
            raw = await self._fetch_exact_bytes(client, url, pin.content_sha256,
                                                budget=budget)
            references = {}
            for path, digest in pin.references:
                ref_url = f"{GITHUB_RAW}/{pin.repo}/{pin.commit}/{path}"
                content = await self._fetch_exact_bytes(client, ref_url, digest,
                                                        budget=budget)
                references[path.removeprefix(pin.entry_path.rsplit("/", 1)[0] + "/")] = content
        if pin.entry_path.endswith("/SKILL.md"):
            try:
                skill_md = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise RemoteImportRefused("invalid_skill") from exc
            if self._extract_frontmatter(skill_md, strict=True).get("name") != skill_slug:
                raise RemoteImportRefused("source_identity_mismatch")
            manifest = None
        else:
            try:
                manifest = self._parse_manifest(raw.decode("utf-8"),
                                                pin.entry_path.rsplit("/", 1)[-1])
            except UnicodeDecodeError as exc:
                raise RemoteImportRefused("invalid_skill") from exc
            if type(manifest) is not dict or manifest.get("name", skill_slug) != skill_slug:
                raise RemoteImportRefused("source_identity_mismatch")
            try:
                skill_md = self._synthesize_skill_md(skill_slug, manifest, source)
            except (TypeError, ValueError) as exc:
                raise RemoteImportRefused("invalid_skill") from exc
        self._check_install(authorization, payload)
        return await self._save_skill(
            skill_slug, source, skill_md_text=skill_md, manifest=manifest,
            provenance={"source_repository": pin.repo, "source_commit": pin.commit,
                        "source_path": pin.entry_path,
                        "content_sha256": pin.content_sha256,
                        "source_files": payload["files"], "quarantined": True},
            reference_files=references,
        )

    def _parse_manifest(self, content: str, filename: str) -> Optional[dict]:
        if filename.endswith(".json"):
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return None
        elif filename.endswith((".yaml", ".yml")):
            try:
                import yaml

                return yaml.safe_load(content)
            except ImportError:
                pass
            except yaml.YAMLError:
                return None
        return None

    async def _save_skill(
        self,
        skill_name: str,
        source: str,
        skill_md_text: Optional[str] = None,
        manifest: Optional[dict] = None,
        skill_md_bytes: Optional[bytes] = None,
        provenance: Optional[dict] = None,
        reference_files: Optional[dict[str, bytes]] = None,
    ) -> bool:
        self.last_refusal = []
        slug = _safe_slug(skill_name)
        if slug is None:
            logger.warning("Rejected skill import: unsafe name %r", skill_name)
            return False
        if skill_md_bytes is not None:
            try:
                verified_text = skill_md_bytes.decode("utf-8")
            except UnicodeDecodeError:
                logger.warning("Rejected verified skill bytes that are not UTF-8")
                return False
            if skill_md_text is not None and skill_md_text != verified_text:
                logger.warning("Rejected mismatched verified skill bytes and text")
                return False
            skill_md_text = verified_text
        target_dir = self.skills_dir / slug
        # Belt and braces: even with the regex, confirm the resolved path is really
        # inside the skills tree before creating anything. A symlinked skills_dir or
        # a future change to the pattern cannot quietly reopen the escape.
        try:
            target_dir.resolve().relative_to(self.skills_dir.resolve())
        except ValueError:
            logger.warning(
                "Rejected skill import: %r resolves outside %s", skill_name, self.skills_dir
            )
            return False

        if skill_md_text is None:
            skill_md_text = self._synthesize_skill_md(skill_name, manifest or {}, source)
        # H350 — the document is checked before its folder exists: a malformed SKILL.md
        # would register under the folder's name with an empty description.
        from .validate import validate_skill_md

        self.last_refusal = validate_skill_md(skill_md_bytes if skill_md_bytes is not None else skill_md_text)
        if self.last_refusal:
            logger.warning("Rejected skill import: its SKILL.md is not valid (%s)",
                           "; ".join(str(p) for p in self.last_refusal))
            return False
        # Sidecar manifest.json records import provenance for list_imported().
        fm = self._extract_frontmatter(skill_md_text)
        meta = manifest or {}
        sidecar = {
            "name": fm.get("name") or meta.get("name", skill_name),
            "description": fm.get("description") or meta.get("description", ""),
            "version": str(fm.get("version") or meta.get("version", "1.0.0")),
            "author": fm.get("author") or meta.get("author", ""),
            "license": fm.get("license", ""),
            "source": source,
            "imported": True,
        }
        if provenance:
            sidecar.update(provenance)
        manifest_bytes = json.dumps(sidecar, indent=2, ensure_ascii=False).encode("utf-8")
        body = skill_md_bytes if skill_md_bytes is not None else skill_md_text.encode("utf-8")
        if reference_files is None:
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "SKILL.md").write_bytes(body)
            (target_dir / "manifest.json").write_bytes(manifest_bytes)
        else:
            # The complete verified directory is prepared away from the live name.
            # An existing owner copy (and its approval) is never replaced here.
            if target_dir.exists() or target_dir.is_symlink():
                return False
            stage = Path(tempfile.mkdtemp(prefix=".hermes-stage-", dir=self.skills_dir))
            try:
                (stage / "SKILL.md").write_bytes(body)
                for relative, content in reference_files.items():
                    if not relative.startswith("references/") or not _safe_reference_path(
                        (provenance or {}).get("source_path", "").removesuffix("SKILL.md") + relative,
                        (provenance or {}).get("source_path", ""),
                    ):
                        return False
                    dest = stage / relative
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(content)
                (stage / "manifest.json").write_bytes(manifest_bytes)
                (stage / "PENDING_REVIEW").write_text(
                    f"source={source}\nsha256={hashlib.sha256(body).hexdigest()}\n",
                    encoding="utf-8",
                )
                if target_dir.exists() or target_dir.is_symlink():
                    return False
                _publish_stage_no_replace(stage, target_dir)
            except OSError:
                logger.warning("Could not atomically save verified Hermes skill '%s'", slug,
                               exc_info=True)
                return False
            finally:
                if stage.exists():
                    shutil.rmtree(stage)

        logger.info(f"Imported skill '{skill_name}' from {source} -> {target_dir}")
        return True

    @staticmethod
    def _synthesize_skill_md(skill_name: str, manifest: dict, source: str) -> str:
        """Build a SKILL.md (frontmatter + body) from a legacy manifest dict."""
        import yaml

        name = manifest.get("name", skill_name)
        fm = {
            "name": name,
            "description": manifest.get("description", ""),
            "version": str(manifest.get("version", "1.0.0")),
            "author": manifest.get("author", ""),
        }
        body = [f"# {name}", ""]
        desc = manifest.get("readme") or manifest.get("description") or ""
        if desc:
            body += [desc, ""]
        prompt = manifest.get("prompt") or manifest.get("instruction") or ""
        if prompt:
            body += ["## Instructions", "", prompt, ""]
        body += [f"*Imported from {source}*", ""]
        fm_text = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()
        return f"---\n{fm_text}\n---\n\n" + "\n".join(body)

    @staticmethod
    def _extract_frontmatter(text: str, *, strict: bool = False) -> dict:
        # The same parse the loader runs (H327): BOM-safe, with the key:value
        # fallback for malformed YAML, so the importer and the loader agree on
        # metadata. ``strict`` drops that fallback: a name only the fallback can
        # find never decides an identity (the Hermes pin gate, a migration slug).
        if not text:
            return {}
        from .frontmatter import split_frontmatter

        data, _body = split_frontmatter(text, lenient=not strict)
        return data if isinstance(data, dict) else {}

    async def _sync_from_hermes(self, category: Optional[str],
                                authorization: RemoteImportAuthorization) -> list[str]:
        pin = _load_hermes_pin()
        if category is not None:
            if not _safe_hermes_category(category):
                logger.warning("Rejected unsafe Hermes category filter")
                return []
            scopes = (f"skills/{category}/", f"optional-skills/{category}/")
            selected = [entry for entry in pin.skills if entry.path.startswith(scopes)]
        else:
            selected = list(pin.skills)
        if not selected:
            return []
        # A bulk sync must not install some entries and then encounter an
        # existing owner copy that this importer refuses to replace.
        if any((self.skills_dir / entry.slug).exists() or
               (self.skills_dir / entry.slug).is_symlink() for entry in selected):
            return []

        payloads = [self._install_payload(
            "hermes", entry.slug,
            RemoteSkillPin(pin.repository, pin.commit, entry.path,
                           entry.content_sha256, entry.files),
            release_tag=pin.release_tag, tree=pin.tree,
        ) for entry in selected]
        for payload in payloads:
            self._check_install(authorization, payload)
        verified = []
        async with self._remote_client(authorization) as client:
            for entry in selected:
                content = await self._fetch_verified_hermes_skill(client, pin, entry)
                verified.append((entry, *content))

        for payload in payloads:
            self._check_install(authorization, payload)
        imported = []
        for (entry, raw, text, references), payload in zip(verified, payloads, strict=True):
            self._check_install(authorization, payload)
            if await self._save_skill(
                entry.slug,
                "hermes",
                skill_md_text=text,
                skill_md_bytes=raw,
                provenance=self._hermes_provenance(pin, entry),
                reference_files=references,
            ):
                imported.append(entry.slug)
        return imported

    async def sync_source(
        self, source: str, category: Optional[str] = None, *,
        pins: tuple[RemoteSkillPin, ...] | None = None,
        authorization: RemoteImportAuthorization | None = None,
    ) -> list[str]:
        authorization = self._require_authorization(authorization)
        if source == "hermes":
            return await self._sync_from_hermes(category, authorization)
        if pins is None:
            raise RemoteImportRefused("missing_pin")
        if type(pins) is not tuple or not pins or len(pins) > 64:
            raise RemoteImportRefused("invalid_pin")
        repo = OPENCLAW_REPO if source == "openclaw" else source
        if any(not isinstance(pin, RemoteSkillPin) or pin.repo != repo for pin in pins):
            raise RemoteImportRefused("invalid_pin")
        if category is not None and not _safe_hermes_category(category):
            raise RemoteImportRefused("invalid_pin")
        imported: list[str] = []
        for pin in pins:
            if category is not None and f"/{category}/" not in pin.entry_path:
                continue
            name = pin.entry_path.rsplit("/", 2)[-2]
            if await self._import_from_github(
                repo, name, pin=pin, authorization=authorization,
                source="openclaw" if source == "openclaw" else repo.rsplit("/", 1)[-1],
            ):
                imported.append(name)
        return imported

    async def import_local_skill(
        self,
        skill_dir: Path,
        source: str,
        *,
        dry_run: bool = False,
        overwrite: bool = False,
        expected_sha256: Optional[str] = None,
        backup_dir: Optional[Path] = None,
        revoke_approval: Optional[Callable[[Path], bool]] = None,
        source_root: Optional[Path] = None,
    ) -> dict:
        """Copy one local ``SKILL.md`` (a Hermes/OpenClaw/Claude Code install) into
        the skills tree, **quarantined** — see ``_import_local_skill`` below.

        Returns ``{"slug", "status", "reason", ...}`` with ``status`` one of
        ``imported`` / ``would_import`` (dry-run) / ``unchanged`` / ``changed`` /
        ``reimported`` / ``skipped`` / ``rejected``. When the target already exists
        the call re-detects instead of blindly skipping (H344): a target whose
        ``manifest.json`` records *this* source file reads ``unchanged`` (same
        digest) or ``changed`` (``old_sha256``/``new_sha256`` plus a bounded line
        diff); any other existing target is ``skipped``/``exists``.

        ``overwrite=True`` re-imports a ``changed`` skill only — never a skill this
        source did not import — and requires ``backup_dir`` (the current copy is
        kept there) and ``revoke_approval`` (the owner's prior approval of the old
        bytes is dropped; the skill goes back to ``PENDING_REVIEW``).
        ``expected_sha256`` binds a write to the bytes an authorizer saw: a source
        edited in between is refused. ``injection_flags`` lists
        ``quarantine.detect_injection`` hits for the owner's review card; a hit
        does not block the import because the skill is quarantined either way.
        ``source_root`` (the install root, e.g. ``~/.hermes``) lets a re-run follow
        a skill whose folder moved inside that install: the recorded file is gone
        and this one declares the same name, so it reads ``unchanged``/``changed``
        with reason ``source_moved`` and ``moved_from``, and a re-import records
        the new path. Without it a moved source reads ``skipped``/``exists``.
        A dry run touches nothing on disk.
        """
        return await _import_local_skill(
            self,
            skill_dir,
            source,
            dry_run=dry_run,
            overwrite=overwrite,
            expected_sha256=expected_sha256,
            backup_dir=backup_dir,
            revoke_approval=revoke_approval,
            source_root=source_root,
        )

    def list_imported(self) -> list[dict]:
        imported = []
        if not self.skills_dir.exists():
            return imported
        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            manifest_path = skill_dir / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, IOError):
                continue
            if data.get("imported") or data.get("source") in ("hermes", "openclaw"):
                imported.append(data)
        return imported


# ── Local-install migration: `nerva import --from hermes|openclaw|claude-code` ──
#
# The importer above pulls *pinned* skills from GitHub. This section is the other
# direction of the switching-cost problem: an owner who already runs Hermes Agent,
# OpenClaw or Claude Code has a home directory full of skills, persona files,
# memory notes and channel tokens. ``detect_sources`` finds those installs
# (read-only, never follows symlinks) and ``SkillImporter.import_local_skill``
# copies one SKILL.md into the skills tree **quarantined**: the loader's
# ``PENDING_REVIEW`` marker means the skill is registered for review but never
# exec'd in-process until the owner approves it (CDX-8). Persona / memory / token
# handling lives in ``scripts/nerva_import.py`` — memory facts are tainted and
# cross the ``kg.write`` kernel kind there; nothing here writes outside the
# skills tree.

MIGRATION_SOURCES: tuple[str, ...] = ("hermes", "openclaw", "claude-code")

# Documented on-disk layouts (research: docs/research/2026-09-06-hermes-and-field-gap-matrix.md).
# Globs are relative to the install root; a missing file simply yields nothing.
_MIGRATION_LAYOUTS: dict[str, dict[str, tuple[str, ...]]] = {
    "hermes": {
        "root": (".hermes",),
        "persona": ("SOUL.md", "memories/USER.md"),
        "memory": ("memories/MEMORY.md",),
        "tokens": (".env",),
        "skills": ("skills",),
    },
    "openclaw": {
        "root": (".openclaw",),
        "persona": ("workspace/SOUL.md", "workspace/USER.md", "workspace/IDENTITY.md"),
        "memory": ("workspace/MEMORY.md",),
        "tokens": ("openclaw.json", ".env"),
        "skills": ("skills", "workspace/skills"),
    },
    "claude-code": {
        "root": (".claude",),
        "persona": ("CLAUDE.md",),
        "memory": ("projects/*/memory/MEMORY.md",),
        "tokens": ("settings.json",),
        "skills": ("skills",),
    },
}
_MAX_SKILL_MD_BYTES = 256 * 1024
_MAX_SKILL_SCAN_DEPTH = 3
_MAX_SKILLS_PER_SOURCE = 500


@dataclass(frozen=True)
class DetectedSource:
    """One detected foreign install: which files exist, grouped by what they become.

    Paths are absolute and already vetted as regular files/directories (no symlinks,
    no reparse points) — the CLI and the runner can trust them without re-checking.
    """

    source: str
    root: Path
    persona_files: tuple[Path, ...] = ()
    memory_files: tuple[Path, ...] = ()
    token_files: tuple[Path, ...] = ()
    skill_dirs: tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        if self.source not in MIGRATION_SOURCES:
            raise ValueError(f"unknown migration source: {self.source!r}")
        if not isinstance(self.root, Path):
            raise TypeError("root must be a Path")
        for group in (self.persona_files, self.memory_files, self.token_files, self.skill_dirs):
            if not isinstance(group, tuple) or not all(isinstance(p, Path) for p in group):
                raise TypeError("file groups must be tuples of Path")

    @property
    def empty(self) -> bool:
        return not (self.persona_files or self.memory_files or self.token_files or self.skill_dirs)

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "root": str(self.root),
            "persona_files": [str(p) for p in self.persona_files],
            "memory_files": [str(p) for p in self.memory_files],
            "token_files": [str(p) for p in self.token_files],
            "skill_dirs": [str(p) for p in self.skill_dirs],
        }


def _is_plain_file(path: Path, max_bytes: int = _MAX_SKILL_MD_BYTES) -> bool:
    try:
        if path.is_symlink() or not path.is_file():
            return False
        return path.stat().st_size <= max_bytes
    except OSError:
        return False


def _is_plain_dir(path: Path) -> bool:
    try:
        return path.is_dir() and not path.is_symlink()
    except OSError:
        return False


def _glob_plain_files(root: Path, patterns: tuple[str, ...]) -> tuple[Path, ...]:
    found: list[Path] = []
    for pattern in patterns:
        candidates = sorted(root.glob(pattern)) if "*" in pattern else [root / pattern]
        for candidate in candidates:
            if _is_plain_file(candidate) and candidate not in found:
                found.append(candidate)
    return tuple(found)


def _scan_skill_dirs(skills_root: Path) -> tuple[Path, ...]:
    """Directories holding a plain ``SKILL.md`` under *skills_root* (bounded walk)."""
    if not _is_plain_dir(skills_root):
        return ()
    found: list[Path] = []
    stack: list[tuple[Path, int]] = [(skills_root, 0)]
    while stack and len(found) < _MAX_SKILLS_PER_SOURCE:
        current, depth = stack.pop()
        try:
            children = sorted(current.iterdir(), reverse=True)
        except OSError:
            continue
        for child in children:
            if not _is_plain_dir(child) or child.name.startswith("."):
                continue
            if _is_plain_file(child / "SKILL.md"):
                found.append(child)
            elif depth + 1 < _MAX_SKILL_SCAN_DEPTH:
                stack.append((child, depth + 1))
    return tuple(sorted(found))


def _home_base(home: Optional[Path]) -> Path:
    """*home* (default ``~``) as an absolute, resolved directory.

    Resolved once, here: every path detection hands out — and so every
    ``source_path`` an import records — is absolute, so a later re-run from another
    working directory (or with ``--home`` spelled differently) still recognises the
    same source file instead of misreporting it as removed. Only the base is
    resolved; the install root and everything below it are still checked with
    ``lstat`` semantics, so a linked install is refused exactly as before.
    """
    base = Path(home).expanduser() if home is not None else Path.home()
    return base.resolve()


def install_root(source: str, home: Optional[Path] = None) -> Path:
    """Where *source*'s install lives under *home* (default ``~``); it may not exist."""
    if source not in MIGRATION_SOURCES:
        raise ValueError(f"unknown migration source: {source!r}")
    return _home_base(home) / _MIGRATION_LAYOUTS[source]["root"][0]


def detect_sources(home: Optional[Path] = None, only: Optional[str] = None) -> list[DetectedSource]:
    """Find Hermes / OpenClaw / Claude Code installs under *home* (default ``~``).

    Read-only. Returns one :class:`DetectedSource` per install whose root directory
    exists (possibly ``empty`` when nothing importable is inside). *only* narrows
    to a single source name; an unknown name raises ``ValueError`` so a CLI typo
    cannot silently detect nothing.
    """
    base = _home_base(home)
    if only is not None and only not in MIGRATION_SOURCES:
        raise ValueError(f"unknown migration source: {only!r}")
    detected: list[DetectedSource] = []
    for source in MIGRATION_SOURCES:
        if only is not None and source != only:
            continue
        layout = _MIGRATION_LAYOUTS[source]
        root = install_root(source, base)
        if not _is_plain_dir(root):
            continue
        skill_dirs: list[Path] = []
        for rel in layout["skills"]:
            for skill_dir in _scan_skill_dirs(root / rel):
                if skill_dir not in skill_dirs:
                    skill_dirs.append(skill_dir)
        detected.append(
            DetectedSource(
                source=source,
                root=root,
                persona_files=_glob_plain_files(root, layout["persona"]),
                memory_files=_glob_plain_files(root, layout["memory"]),
                token_files=_glob_plain_files(root, layout["tokens"]),
                skill_dirs=tuple(skill_dirs),
            )
        )
    return detected


def _local_skill_result(slug: Optional[str], status: str, reason: str = "", **extra) -> dict:
    result = {"slug": slug, "status": status, "reason": reason}
    result.update(extra)
    return result


# ── H344: re-detect / diff after import ──────────────────────────────────────
#
# Import-once stays the only way a foreign skill enters the skills tree: a
# live-scanned foreign directory would be a folder someone else's tool writes
# into, a trust boundary Nerva would have to re-check on every turn. What a re-run
# adds is *noticing*. The ``manifest.json`` sidecar already records the source
# file and the digest of the bytes imported, so a later run reports each skill as
# ``unchanged`` / ``changed`` (both digests + a bounded line diff) /
# ``source_removed``, and re-imports a changed one only on an explicit owner
# request: the current copy is backed up outside the tree, the skill goes back to
# ``PENDING_REVIEW`` before the new bytes land, and the owner's approval of the
# old bytes is revoked.

_MAX_DIFF_PREVIEW_LINES = 40
_MAX_DIFF_LINE_CHARS = 200
_MAX_RESCAN_DIRS = 2000
# Approval-time artefacts that vouch for the OLD bytes: the signature
# ``approve_generated_skill`` mints and the legacy in-tree approval marker.
_REIMPORT_CLEARED_CONTROLS: tuple[str, ...] = ("SKILL.sig", "OWNER_APPROVED_IN_PROCESS")
_REIMPORT_CONTROL_FILES: tuple[str, ...] = (
    "SKILL.md",
    "manifest.json",
    "PENDING_REVIEW",
    *_REIMPORT_CLEARED_CONTROLS,
)


def _same_path(a: str, b: str) -> bool:
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except (OSError, ValueError):
        return False


def _lexically_inside(path, root) -> bool:
    """*path*, normalised without touching the filesystem, lies under *root*."""
    try:
        lexical = Path(os.path.normcase(os.path.abspath(path)))
        roots = {
            Path(os.path.normcase(os.path.abspath(root))),
            Path(os.path.normcase(os.path.realpath(root))),
        }
    except (OSError, ValueError):
        return False
    return any(lexical.is_relative_to(candidate) for candidate in roots)


def _really_inside(path, root) -> bool:
    """*path*, with every existing link resolved, still lies under *root*."""
    try:
        real = Path(os.path.normcase(os.path.realpath(path)))
        return real.is_relative_to(Path(os.path.normcase(os.path.realpath(root))))
    except (OSError, ValueError):
        return False


def _source_moved(record: dict, skill_md: Path, source_root: Optional[Path]) -> bool:
    """The recorded source file is gone and *skill_md* is where it went.

    A Hermes category reorganisation moves ``skills/github/x`` to
    ``skills/devops/x`` and keeps the declared name. Both paths must lie inside the
    same install (lexically and with links resolved) and the recorded path must no
    longer exist at all: while it does, a second folder declaring the same name is
    a different skill, never the tracked one.
    """
    if source_root is None:
        return False
    recorded = record["source_path"]
    for path in (recorded, skill_md):
        if not (_lexically_inside(path, source_root) and _really_inside(path, source_root)):
            return False
    try:
        return not os.path.lexists(recorded)
    except (OSError, ValueError):
        return False


def _read_import_record(target: Path) -> Optional[dict]:
    """The local-import provenance of *target*, or None when it has none we trust.

    Only a real directory holding a regular (non-link) ``manifest.json`` whose
    ``source_install`` names a migration source, with a recorded ``source_path``
    and a sha256 ``content_sha256``, counts. Anything else is a skill this
    importer did not write: it is reported ``exists`` and never re-imported.
    """
    if not _is_plain_dir(target):
        return None
    sidecar = target / "manifest.json"
    if not _is_plain_file(sidecar):
        return None
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("source_install") not in MIGRATION_SOURCES:
        return None
    source_path = data.get("source_path")
    digest = data.get("content_sha256")
    if not isinstance(source_path, str) or not source_path:
        return None
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        return None
    return data


def _diff_summary(old: bytes, new: bytes) -> dict:
    """Line counts plus a bounded unified-diff preview (imported copy → source)."""
    old_lines = old.decode("utf-8", errors="replace").splitlines()
    new_lines = new.decode("utf-8", errors="replace").splitlines()
    # [2:] drops the ---/+++ file header; a changed line may itself start with "--".
    diff = list(
        difflib.unified_diff(old_lines, new_lines, "imported", "source", lineterm="", n=0)
    )[2:]
    body = [line for line in diff if not line.startswith("@@")]
    return {
        "lines_added": sum(1 for line in body if line.startswith("+")),
        "lines_removed": sum(1 for line in body if line.startswith("-")),
        "preview": [line[:_MAX_DIFF_LINE_CHARS] for line in diff[:_MAX_DIFF_PREVIEW_LINES]],
        "truncated": len(diff) > _MAX_DIFF_PREVIEW_LINES,
    }


def _classify_existing(
    target: Path,
    skill_md: Path,
    source: str,
    raw: bytes,
    digest: str,
    source_root: Optional[Path] = None,
) -> dict:
    """``exists`` / ``unchanged`` / ``changed`` for an already-present *target*.

    A record naming another file of the same install that no longer exists is
    followed to *skill_md* (``moved_from`` + reason ``source_moved``) when
    *source_root* is given; see :func:`_source_moved`.
    """
    record = _read_import_record(target)
    if record is None or record.get("source_install") != source:
        return {"status": "exists"}
    moved: dict = {}
    if not _same_path(record["source_path"], str(skill_md)):
        if not _source_moved(record, skill_md, source_root):
            return {"status": "exists"}
        moved = {"moved_from": record["source_path"], "source_path": str(skill_md)}
    old_digest = record["content_sha256"]
    if old_digest == digest:
        return {"status": "unchanged", **moved}
    current = target / "SKILL.md"
    try:
        local = current.read_bytes() if _is_plain_file(current) else b""
    except OSError:
        local = b""
    return {
        "status": "changed",
        "old_sha256": old_digest,
        "new_sha256": digest,
        # The owner edited the imported copy by hand: a re-import replaces that
        # edit (the backup keeps it), so the report says so up front.
        "local_modified": hashlib.sha256(local).hexdigest() != old_digest,
        "diff": _diff_summary(local, raw),
        **moved,
    }


def _pending_review_text(
    source: str, skill_md: Path, digest: str, flags, previous: str = ""
) -> str:
    text = (
        f"source={source}\nimported_from={skill_md}\nsha256={digest}\n"
        f"injection_flags={len(flags)}\n"
    )
    if previous:
        text += f"previous_sha256={previous}\n"
    return text


def _unique_backup_path(backup_dir: Path, slug: str, old_digest: str) -> Path:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    folder = Path(backup_dir) / slug
    candidate = folder / f"{stamp}-{old_digest[:12]}.SKILL.md"
    counter = 1
    while candidate.exists() or candidate.is_symlink():
        candidate = folder / f"{stamp}-{old_digest[:12]}-{counter}.SKILL.md"
        counter += 1
    return candidate


async def _reimport_local_skill(
    importer: "SkillImporter",
    target: Path,
    skill_md: Path,
    source: str,
    *,
    text: str,
    raw: bytes,
    digest: str,
    flags,
    old_digest: str,
    backup_dir: Optional[Path],
    revoke_approval: Optional[Callable[[Path], bool]],
    local_modified: bool = False,
    moved_from: str = "",
) -> dict:
    slug = target.name
    info = {
        "sha256": digest,
        "old_sha256": old_digest,
        "new_sha256": digest,
        "injection_flags": flags,
        # The owner had edited the imported copy: this re-import replaces that edit
        # and the backup below is where it survives (the CLI names the path).
        "local_modified": bool(local_modified),
    }
    if moved_from:
        info.update(moved_from=moved_from, source_path=str(skill_md))
    if backup_dir is None:
        return _local_skill_result(slug, "rejected", "backup_dir_unset", **info)
    if revoke_approval is None:
        return _local_skill_result(slug, "rejected", "approval_revoker_unset", **info)
    try:
        target.resolve().relative_to(importer.skills_dir.resolve())
    except (OSError, ValueError):
        return _local_skill_result(slug, "rejected", "target_outside_skills_dir", **info)
    for name in _REIMPORT_CONTROL_FILES:
        control = target / name
        if control.is_symlink() or (control.exists() and not control.is_file()):
            return _local_skill_result(slug, "rejected", "target_not_plain", **info)
    current = target / "SKILL.md"
    try:
        old_bytes = current.read_bytes() if current.exists() else b""
    except OSError:
        return _local_skill_result(slug, "rejected", "target_unreadable", **info)

    # 1) The current copy is kept OUTSIDE the skills tree: inside it, the backup
    #    would become part of the skill's reviewed source snapshot.
    try:
        backup = _unique_backup_path(Path(backup_dir), slug, old_digest)
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(old_bytes)
    except OSError:
        return _local_skill_result(slug, "rejected", "backup_failed", **info)

    # 2) Quarantine BEFORE the new bytes land: no loader pass may ever see the new
    #    source without the PENDING_REVIEW marker (CDX-8).
    marker = target / "PENDING_REVIEW"
    marker.write_text(
        _pending_review_text(source, skill_md, digest, flags, old_digest), encoding="utf-8"
    )
    # 3) The approval-time signature and legacy marker vouch for the OLD bytes.
    for name in _REIMPORT_CLEARED_CONTROLS:
        (target / name).unlink(missing_ok=True)

    saved = await importer._save_skill(
        slug,
        source,
        skill_md_text=text,
        skill_md_bytes=raw,
        provenance={
            "source_install": source,
            "source_path": str(skill_md),
            "content_sha256": digest,
            "previous_sha256": old_digest,
            "reimported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "quarantined": True,
        },
    )
    if not saved:
        # Fail closed: the step-2 marker stays, so whatever bytes remain are quarantined.
        return _local_skill_result(
            slug, "rejected", "save_refused", backup_path=str(backup), **info
        )

    # 4) Drop the owner's approval bound to this path: it approved other bytes, and
    #    a later revert to them must not inherit it (DRA-54).
    try:
        revoked = bool(revoke_approval(target))
    except Exception:  # the marker already fails closed; report, never raise
        logger.warning("Approval revoke failed for re-imported skill %s", slug, exc_info=True)
        revoked = False
    return _local_skill_result(
        slug,
        "reimported",
        "",
        quarantined=True,
        approval_revoked=revoked,
        backup_path=str(backup),
        **info,
    )


async def _import_local_skill(
    importer: "SkillImporter",
    skill_dir: Path,
    source: str,
    *,
    dry_run: bool,
    overwrite: bool,
    expected_sha256: Optional[str] = None,
    backup_dir: Optional[Path] = None,
    revoke_approval: Optional[Callable[[Path], bool]] = None,
    source_root: Optional[Path] = None,
) -> dict:
    if source not in MIGRATION_SOURCES:
        return _local_skill_result(None, "rejected", "unknown_source")
    # Absolute before anything is recorded: a relative skill_dir (or --home) would
    # otherwise write a cwd-relative source_path that no later re-run can match.
    skill_md = Path(os.path.abspath(skill_dir)) / "SKILL.md"
    if not _is_plain_file(skill_md):
        return _local_skill_result(None, "rejected", "skill_md_missing_or_not_plain_file")
    try:
        raw = skill_md.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return _local_skill_result(None, "rejected", "skill_md_unreadable")
    frontmatter = SkillImporter._extract_frontmatter(text, strict=True)
    declared = frontmatter.get("name")
    slug = _safe_slug(str(declared) if declared else Path(skill_dir).name)
    if slug is None:
        return _local_skill_result(None, "rejected", "unsafe_skill_name")
    # H350 — a document the loader would misread is refused here, before any dry-run
    # verdict, any backup or any quarantine marker (the re-import path included).
    from .validate import validate_skill_md

    problems = validate_skill_md(raw)
    if problems:
        return _local_skill_result(slug, "rejected", "invalid_skill_md",
                                   problems=[p.as_dict() for p in problems])

    from ..security import quarantine

    flags = quarantine.detect_injection(text)
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        # The bytes moved between the authorizer's look and this write: the grant
        # covered other bytes, so nothing is written.
        return _local_skill_result(
            slug,
            "rejected",
            "source_changed_since_authorized",
            sha256=digest,
            expected_sha256=expected_sha256,
            injection_flags=flags,
        )
    target = importer.skills_dir / slug
    if target.exists() or target.is_symlink():
        state = _classify_existing(target, skill_md, source, raw, digest, source_root)
        status = state.pop("status")
        if status == "exists":
            reason = "exists_not_imported_from_source" if overwrite else "exists"
            return _local_skill_result(
                slug, "skipped", reason, sha256=digest, injection_flags=flags
            )
        moved = "moved_from" in state
        if status == "unchanged":
            return _local_skill_result(
                slug,
                "unchanged",
                "source_moved" if moved else "",
                sha256=digest,
                injection_flags=flags,
                quarantined=(target / "PENDING_REVIEW").exists(),
                **state,
            )
        if dry_run or not overwrite:
            reason = "source_moved" if moved else "source_changed"
            return _local_skill_result(
                slug, "changed", reason, sha256=digest, injection_flags=flags, **state
            )
        return await _reimport_local_skill(
            importer,
            target,
            skill_md,
            source,
            text=text,
            raw=raw,
            digest=digest,
            flags=flags,
            old_digest=state["old_sha256"],
            backup_dir=backup_dir,
            revoke_approval=revoke_approval,
            local_modified=state["local_modified"],
            moved_from=state.get("moved_from", ""),
        )
    if dry_run:
        return _local_skill_result(
            slug, "would_import", "", sha256=digest, injection_flags=flags, quarantined=True
        )
    saved = await importer._save_skill(
        slug,
        source,
        skill_md_text=text,
        skill_md_bytes=raw,
        provenance={
            "source_install": source,
            "source_path": str(skill_md),
            "content_sha256": digest,
            "quarantined": True,
        },
    )
    if not saved:
        return _local_skill_result(slug, "rejected", "save_refused", sha256=digest)
    # CDX-8 quarantine: registered for review, never exec'd until owner approval
    # (``SkillLoader.approve_generated_skill``). A foreign install's skill is
    # untrusted code by definition — flags or not.
    (target / "PENDING_REVIEW").write_text(
        _pending_review_text(source, skill_md, digest, flags), encoding="utf-8"
    )
    return _local_skill_result(
        slug, "imported", "", sha256=digest, injection_flags=flags, quarantined=True
    )


def rescan_imported(
    skills_dir: Path,
    source: Optional[str] = None,
    *,
    home: Optional[Path] = None,
    root: Optional[Path] = None,
) -> list[dict]:
    """Imported skills whose recorded source is gone or now declares another name.

    Read-only (H344). Walks the direct children of *skills_dir* (bounded, never
    through a link) and, for every local-import record of *source* (or of any
    migration source), reports ``source_removed`` when the recorded ``SKILL.md`` is
    no longer a regular file, ``source_renamed`` when it now declares a different
    skill name (a re-run imports it under the new slug), and ``source_unreadable``
    when it can no longer be read within the import bound. A still-matching source
    yields no row: the per-skill re-detect covers it. Nothing is deleted: removing
    an imported skill stays the owner's decision.

    A record is only followed inside its own install: *root* (one source's install
    root, e.g. a ``DetectedSource.root``) or else ``install_root(source, home)``.
    ``manifest.json`` lives in the skills tree, so a record naming a file anywhere
    else — lexically, or once links are resolved — is reported ``source_untrusted``
    and that file is never opened (its frontmatter never surfaces as ``new_slug``).
    """
    if source is not None and source not in MIGRATION_SOURCES:
        raise ValueError(f"unknown migration source: {source!r}")
    if root is not None and source is None:
        raise ValueError("root names one install: pass the source it belongs to")
    base = Path(skills_dir)
    if not _is_plain_dir(base):
        return []
    try:
        children = sorted(base.iterdir())[:_MAX_RESCAN_DIRS]
    except OSError:
        return []
    rows: list[dict] = []
    for target in children:
        record = _read_import_record(target)
        if record is None or (source is not None and record["source_install"] != source):
            continue
        trusted_root = root if root is not None else install_root(record["source_install"], home)
        source_path = Path(record["source_path"])
        info = {"source_path": str(source_path), "sha256": record["content_sha256"]}
        if not _lexically_inside(source_path, trusted_root):
            rows.append(
                _local_skill_result(
                    target.name, "source_untrusted", "source_path_outside_install", **info
                )
            )
            continue
        try:
            linked = source_path.is_symlink()
            missing = not linked and not source_path.exists()
            plain = not linked and source_path.is_file()
        except OSError:
            missing, plain = True, False
        if missing:
            rows.append(
                _local_skill_result(target.name, "source_removed", "source_path_missing", **info)
            )
            continue
        if not plain:
            rows.append(
                _local_skill_result(target.name, "source_removed", "source_not_plain_file", **info)
            )
            continue
        if not _really_inside(source_path, trusted_root):
            # A linked directory on the way out of the install: never read through it.
            rows.append(
                _local_skill_result(
                    target.name, "source_untrusted", "source_path_outside_install", **info
                )
            )
            continue
        if not _is_plain_file(source_path):
            rows.append(
                _local_skill_result(target.name, "source_unreadable", "skill_md_too_large", **info)
            )
            continue
        try:
            text = source_path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            rows.append(
                _local_skill_result(target.name, "source_unreadable", "skill_md_unreadable", **info)
            )
            continue
        declared = SkillImporter._extract_frontmatter(text, strict=True).get("name")
        slug = _safe_slug(str(declared) if declared else source_path.parent.name)
        if slug != target.name:
            rows.append(
                _local_skill_result(
                    target.name, "source_renamed", "declared_name_changed", new_slug=slug, **info
                )
            )
    return rows
