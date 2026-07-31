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

import json
import logging
import re
from pathlib import Path
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

HERMES_REPO = "NousResearch/hermes-agent"
HERMES_SKILLS_PATH = "main/skills"
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


class SkillImporter:
    def __init__(self, skills_dir: str = "skills"):
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    async def import_from_hermes(self, skill_name: str) -> bool:
        return await self._import_from_github(
            HERMES_REPO, HERMES_SKILLS_PATH, skill_name, source="hermes"
        )

    async def import_from_openclaw(self, skill_name: str) -> bool:
        return await self._import_from_github(
            OPENCLAW_REPO, OPENCLAW_SKILLS_PATH, skill_name, source="openclaw"
        )

    async def import_from_github(self, repo: str, skill_name: str, path: str = "main/skills") -> bool:
        return await self._import_from_github(repo, path, skill_name, source=repo.split("/")[-1])

    async def _import_from_github(self, repo: str, base_path: str, skill_name: str, source: str) -> bool:
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
    ) -> bool:
        slug = _safe_slug(skill_name)
        if slug is None:
            logger.warning("Rejected skill import: unsafe name %r", skill_name)
            return False
        target_dir = self.skills_dir / slug
        # Belt and braces: even with the regex, confirm the resolved path is really
        # inside the skills tree before creating anything. A symlinked skills_dir or
        # a future change to the pattern cannot quietly reopen the escape.
        try:
            target_dir.resolve().relative_to(self.skills_dir.resolve())
        except ValueError:
            logger.warning("Rejected skill import: %r resolves outside %s",
                           skill_name, self.skills_dir)
            return False
        target_dir.mkdir(parents=True, exist_ok=True)

        if skill_md_text is None:
            skill_md_text = self._synthesize_skill_md(skill_name, manifest or {}, source)

        # Write SKILL.md so the SkillLoader (which only discovers SKILL.md) loads it.
        (target_dir / "SKILL.md").write_text(skill_md_text, encoding="utf-8")

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

    async def sync_source(self, source: str, category: Optional[str] = None) -> list[str]:
        try:
            import httpx
        except ImportError:
            raise SkillImportError("httpx required for skill import")

        repo = HERMES_REPO if source == "hermes" else OPENCLAW_REPO if source == "openclaw" else source
        skills_path = HERMES_SKILLS_PATH if source == "hermes" else OPENCLAW_SKILLS_PATH if source == "openclaw" else "main/skills"

        if "/" not in repo:
            repo = f"github/{repo}"

        branch, subdir = self._split_base_path(skills_path)

        # Walk the recursive tree and import every <…>/<skill>/SKILL.md found
        # under subdir (optionally scoped to a category). This handles the
        # category-nested Hermes layout, which a shallow contents listing misses.
        url = f"{GITHUB_API}/repos/{repo}/git/trees/{branch}?recursive=1"
        scope = f"{subdir}/{category}/" if (subdir and category) else (f"{subdir}/" if subdir else "")

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
