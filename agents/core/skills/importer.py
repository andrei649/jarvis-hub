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

import hashlib
import hmac
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional

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

HERMES_REPO = "NousResearch/hermes-agent"
HERMES_PIN_RELEASE_TAG = "v2026.8.3"
HERMES_PIN_COMMIT = "3c27eb6234bf91b8ceee9e9071591b31e9b148cb"
HERMES_PIN_TREE = "b217767ccb994605dad522e693fa1b4cdbc2f352"
HERMES_PIN_PATH = Path(__file__).with_name("hermes_pin_v1.json")
OPENCLAW_REPO = "openclaw/skills"
OPENCLAW_SKILLS_PATH = "main/skills"

GITHUB_RAW = "https://raw.githubusercontent.com"
GITHUB_API = "https://api.github.com"


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
    if len(parts) < 3 or parts[0] != "skills" or parts[-1] != "SKILL.md":
        return False
    if parts[-2] != slug or any(part in ("", ".", "..") for part in parts):
        return False
    return all(_SLUG_RE.fullmatch(part) for part in parts[1:-1])


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
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
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
        _require_exact_keys(item, {"slug", "path", "content_sha256"}, "skill entry")
        slug = item["slug"]
        path = item["path"]
        digest = item["content_sha256"]
        if not isinstance(slug, str) or _safe_slug(slug) != slug:
            raise SkillImportError("Hermes pin contains an unsafe skill slug")
        if not _safe_pin_path(path, slug):
            raise SkillImportError("Hermes pin contains an unsafe or mismatched path")
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise SkillImportError("Hermes pin contains an invalid content digest")
        if slug in slugs or path in paths:
            raise SkillImportError("Hermes pin contains duplicate skill identities")
        slugs.add(slug)
        paths.add(path)
        entries.append(_HermesPinEntry(slug=slug, path=path, content_sha256=digest))

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
    def __init__(self, skills_dir: str = "skills"):
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    async def import_from_hermes(self, skill_name: str) -> bool:
        skill_slug = _safe_slug(skill_name)
        if skill_slug is None:
            logger.warning("Rejected Hermes skill import: unsafe name %r", skill_name)
            return False

        pin = _load_hermes_pin()
        entry = next((item for item in pin.skills if item.slug == skill_slug), None)
        if entry is None:
            logger.warning("Skill '%s' is not in the Hermes pin allowlist", skill_slug)
            return False

        try:
            import httpx
        except ImportError:
            raise SkillImportError("httpx required for skill import")

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            verified = await self._fetch_verified_hermes_skill(client, pin, entry)
        if verified is None:
            return False
        raw, text = verified
        return await self._save_skill(
            skill_name,
            "hermes",
            skill_md_text=text,
            skill_md_bytes=raw,
            provenance=self._hermes_provenance(pin, entry),
        )

    async def import_from_openclaw(self, skill_name: str) -> bool:
        return await self._import_from_github(
            OPENCLAW_REPO, OPENCLAW_SKILLS_PATH, skill_name, source="openclaw"
        )

    async def import_from_github(
        self, repo: str, skill_name: str, path: str = "main/skills"
    ) -> bool:
        return await self._import_from_github(repo, path, skill_name, source=repo.split("/")[-1])

    @staticmethod
    async def _fetch_verified_hermes_skill(client, pin: _HermesPin, entry: _HermesPinEntry):
        url = f"{GITHUB_RAW}/{pin.repository}/{pin.commit}/{entry.path}"
        try:
            response = await client.get(url)
            if response.status_code != 200:
                logger.warning(
                    "Hermes pinned content is unavailable for '%s': %s",
                    entry.slug,
                    response.status_code,
                )
                return None
            if str(getattr(response, "url", "")) != url:
                logger.warning("Hermes response URL mismatch for '%s'", entry.slug)
                return None
            raw = response.content
            if not isinstance(raw, bytes):
                logger.warning("Hermes response body is not raw bytes for '%s'", entry.slug)
                return None
            digest = hashlib.sha256(raw).hexdigest()
            if not hmac.compare_digest(digest, entry.content_sha256):
                logger.warning("Hermes content digest mismatch for '%s'", entry.slug)
                return None
            text = raw.decode("utf-8")
            if SkillImporter._extract_frontmatter(text).get("name") != entry.slug:
                logger.warning("Hermes content identity mismatch for '%s'", entry.slug)
                return None
        except UnicodeDecodeError:
            logger.warning("Hermes pinned content is not UTF-8 for '%s'", entry.slug)
            return None
        except Exception as exc:
            logger.debug("Failed to fetch pinned Hermes skill '%s': %s", entry.slug, exc)
            return None
        return raw, text

    @staticmethod
    def _hermes_provenance(pin: _HermesPin, entry: _HermesPinEntry) -> dict[str, str]:
        return {
            "source_repository": pin.repository,
            "source_release_tag": pin.release_tag,
            "source_commit": pin.commit,
            "source_tree": pin.tree,
            "source_path": entry.path,
            "content_sha256": entry.content_sha256,
        }

    async def _import_from_github(
        self, repo: str, base_path: str, skill_name: str, source: str
    ) -> bool:
        try:
            import httpx
        except ImportError:
            raise SkillImportError("httpx required for skill import")

        # Validate before any network call: this slug is interpolated into the raw
        # GitHub URL path, so an unchecked name could climb it or graft on a query.
        skill_slug = _safe_slug(skill_name)
        if skill_slug is None:
            logger.warning("Rejected skill import: unsafe name %r", skill_name)
            return False
        branch, subdir = self._split_base_path(base_path)

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            # 1. SKILL.md in a flat layout: <subdir>/<slug>/SKILL.md
            skill_md = await self._fetch_skill_md_flat(client, repo, branch, subdir, skill_slug)

            # 2. SKILL.md nested under a category: <subdir>/<category>/<slug>/SKILL.md.
            #    The real Hermes repo nests skills one level below the category,
            #    so locate the file via the recursive git-tree listing.
            if skill_md is None:
                found = await self._locate_skill_in_tree(client, repo, branch, subdir, skill_slug)
                if found:
                    skill_md = await self._fetch_raw(client, repo, branch, found)

            if skill_md is not None:
                return await self._save_skill(skill_name, source, skill_md_text=skill_md)

            # 3. Legacy fallback: manifest.json / manifest.yaml
            manifest = await self._fetch_manifest(client, repo, branch, subdir, skill_slug)
            if manifest:
                return await self._save_skill(skill_name, source, manifest=manifest)

        logger.warning(f"Skill '{skill_name}' not found in {source}")
        return False

    @staticmethod
    def _split_base_path(base_path: str) -> tuple[str, str]:
        """Split e.g. ``main/skills`` into (branch="main", subdir="skills")."""
        parts = base_path.strip("/").split("/", 1)
        branch = parts[0] if parts and parts[0] else "main"
        subdir = parts[1] if len(parts) > 1 else ""
        return branch, subdir

    async def _fetch_raw(self, client, repo: str, branch: str, path: str) -> Optional[str]:
        url = f"{GITHUB_RAW}/{repo}/{branch}/{path.lstrip('/')}"
        try:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.text
        except Exception as e:  # network / transient — try the next candidate
            logger.debug(f"Failed to fetch {url}: {e}")
        return None

    async def _fetch_skill_md_flat(self, client, repo, branch, subdir, slug) -> Optional[str]:
        rel = f"{subdir}/{slug}/SKILL.md" if subdir else f"{slug}/SKILL.md"
        return await self._fetch_raw(client, repo, branch, rel)

    async def _locate_skill_in_tree(self, client, repo, branch, subdir, slug) -> Optional[str]:
        """Find ``…/<slug>/SKILL.md`` anywhere under ``subdir`` via the git tree."""
        url = f"{GITHUB_API}/repos/{repo}/git/trees/{branch}?recursive=1"
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None
            tree = resp.json().get("tree", [])
        except Exception as e:
            logger.debug(f"Failed to list tree for {repo}@{branch}: {e}")
            return None

        suffix = f"/{slug}/SKILL.md"
        prefix = f"{subdir}/" if subdir else ""
        matches = [
            item["path"]
            for item in tree
            if item.get("type") == "blob"
            and item.get("path", "").endswith(suffix)
            and item.get("path", "").startswith(prefix)
        ]
        # Prefer the shallowest match when a slug appears more than once.
        matches.sort(key=lambda p: p.count("/"))
        return matches[0] if matches else None

    async def _fetch_manifest(self, client, repo, branch, subdir, slug) -> Optional[dict]:
        base = f"{subdir}/{slug}" if subdir else slug
        for fname in ("manifest.json", "manifest.yaml", "manifest.yml"):
            text = await self._fetch_raw(client, repo, branch, f"{base}/{fname}")
            if text:
                data = self._parse_manifest(text, fname)
                if data:
                    return data
        return None

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
        provenance: Optional[dict[str, str]] = None,
    ) -> bool:
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
        target_dir.mkdir(parents=True, exist_ok=True)

        if skill_md_text is None:
            skill_md_text = self._synthesize_skill_md(skill_name, manifest or {}, source)

        # Preserve verified upstream bytes exactly. Generic imports retain their
        # existing text-write behavior.
        if skill_md_bytes is None:
            (target_dir / "SKILL.md").write_text(skill_md_text, encoding="utf-8")
        else:
            (target_dir / "SKILL.md").write_bytes(skill_md_bytes)

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
        (target_dir / "manifest.json").write_text(
            json.dumps(sidecar, indent=2, ensure_ascii=False), encoding="utf-8"
        )

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
    def _extract_frontmatter(text: str) -> dict:
        if not text or not text.startswith("---"):
            return {}
        lines = text.split("\n")
        if lines[0].strip() != "---":
            return {}
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                try:
                    import yaml

                    data = yaml.safe_load("\n".join(lines[1:i]))
                    return data if isinstance(data, dict) else {}
                except Exception:
                    return {}
        return {}

    async def _sync_from_hermes(self, category: Optional[str]) -> list[str]:
        pin = _load_hermes_pin()
        if category is not None:
            if not _safe_hermes_category(category):
                logger.warning("Rejected unsafe Hermes category filter")
                return []
            scope = f"skills/{category}/"
            selected = [entry for entry in pin.skills if entry.path.startswith(scope)]
        else:
            selected = list(pin.skills)
        if not selected:
            return []

        try:
            import httpx
        except ImportError:
            raise SkillImportError("httpx required for skill import")

        verified = []
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            for entry in selected:
                content = await self._fetch_verified_hermes_skill(client, pin, entry)
                if content is None:
                    return []
                verified.append((entry, *content))

        imported = []
        for entry, raw, text in verified:
            if await self._save_skill(
                entry.slug,
                "hermes",
                skill_md_text=text,
                skill_md_bytes=raw,
                provenance=self._hermes_provenance(pin, entry),
            ):
                imported.append(entry.slug)
        return imported

    async def sync_source(self, source: str, category: Optional[str] = None) -> list[str]:
        if source == "hermes":
            return await self._sync_from_hermes(category)

        try:
            import httpx
        except ImportError:
            raise SkillImportError("httpx required for skill import")

        repo = OPENCLAW_REPO if source == "openclaw" else source
        skills_path = OPENCLAW_SKILLS_PATH if source == "openclaw" else "main/skills"

        if "/" not in repo:
            repo = f"github/{repo}"

        branch, subdir = self._split_base_path(skills_path)

        # Walk the recursive tree and import every <…>/<skill>/SKILL.md found
        # under subdir (optionally scoped to a category). This handles the
        # category-nested Hermes layout, which a shallow contents listing misses.
        url = f"{GITHUB_API}/repos/{repo}/git/trees/{branch}?recursive=1"
        scope = (
            f"{subdir}/{category}/" if (subdir and category) else (f"{subdir}/" if subdir else "")
        )

        imported: list[str] = []
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.warning(f"Failed to list skills from {source}: {resp.status_code}")
                    return imported
                tree = resp.json().get("tree", [])
            except Exception as e:
                logger.warning(f"Failed to sync {source}: {e}")
                return imported

            seen: set[str] = set()
            for item in tree:
                path = item.get("path", "")
                if item.get("type") != "blob" or not path.endswith("/SKILL.md"):
                    continue
                if scope and not path.startswith(scope):
                    continue
                name = path[: -len("/SKILL.md")].rsplit("/", 1)[-1]
                if name in seen:
                    continue
                seen.add(name)
                if await self._import_from_github(repo, skills_path, name, source):
                    imported.append(name)

        return imported

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
