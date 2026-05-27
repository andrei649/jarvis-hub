"""
importer.py — Import skills from Hermes Agent, OpenClaw, agentskills.io.

Port of OpenJarvis's skill import system to pure Python.
Supports importing skills from:
- Hermes Agent (GitHub: NousResearch/hermes-agent)
- OpenClaw (GitHub: openclaw/skills)
- Any GitHub repo with agentskills.io-compatible manifests
"""

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger("jarvis.skills.importer")

HERMES_REPO = "NousResearch/hermes-agent"
HERMES_SKILLS_PATH = "main/skills"
OPENCLAW_REPO = "openclaw/skills"
OPENCLAW_SKILLS_PATH = "main/skills"

GITHUB_RAW = "https://raw.githubusercontent.com"
GITHUB_API = "https://api.github.com"


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

        skill_path = skill_name.lower().replace(" ", "-")

        urls = [
            f"{GITHUB_RAW}/{repo}/{base_path}/{skill_path}/manifest.json",
            f"{GITHUB_RAW}/{repo}/{base_path}/{skill_path}/manifest.yaml",
            f"{GITHUB_RAW}/{repo}/{base_path}/{skill_path}.json",
            f"{GITHUB_RAW}/{repo}/{base_path}/{skill_path}.yaml",
            f"{GITHUB_API}/repos/{repo}/contents/{base_path}/{skill_path}",
        ]

        async with httpx.AsyncClient(timeout=15.0) as client:
            manifest_data = None
            for url in urls:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        if "api.github.com" in url:
                            items = resp.json()
                            for item in items:
                                if item["name"] in ("manifest.json", "manifest.yaml", "manifest.yml"):
                                    file_resp = await client.get(item["download_url"])
                                    if file_resp.status_code == 200:
                                        manifest_data = self._parse_manifest(file_resp.text, item["name"])
                                        break
                        else:
                            manifest_data = self._parse_manifest(resp.text, url.split("/")[-1])
                        if manifest_data:
                            break
                except Exception as e:
                    logger.debug(f"Failed to fetch {url}: {e}")

            if not manifest_data:
                logger.warning(f"Skill '{skill_name}' not found in {source}")
                return False

            return await self._save_skill(skill_name, manifest_data, source)

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

    async def _save_skill(self, skill_name: str, manifest: dict, source: str) -> bool:
        target_dir = self.skills_dir / skill_name.lower().replace(" ", "-")
        target_dir.mkdir(parents=True, exist_ok=True)

        manifest_path = target_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({
                "name": manifest.get("name", skill_name),
                "description": manifest.get("description", ""),
                "version": manifest.get("version", "1.0.0"),
                "source": source,
                "author": manifest.get("author", ""),
                "tools": manifest.get("tools", manifest.get("capabilities", [])),
                "dependencies": manifest.get("dependencies", []),
                "prompt": manifest.get("prompt", manifest.get("instruction", "")),
                "command": manifest.get("command", manifest.get("trigger", "")),
                "agents": manifest.get("agents", []),
            }, f, indent=2, ensure_ascii=False)

        readme = manifest.get("readme", manifest.get("description", ""))
        if readme:
            readme_path = target_dir / "README.md"
            with open(readme_path, "w", encoding="utf-8") as f:
                f.write(f"# {skill_name}\n\n{readme}\n\n*Imported from {source}*")

        logger.info(f"Imported skill '{skill_name}' from {source} -> {target_dir}")
        return True

    async def sync_source(self, source: str, category: Optional[str] = None) -> list[str]:
        try:
            import httpx
        except ImportError:
            raise SkillImportError("httpx required for skill import")

        repo = HERMES_REPO if source == "hermes" else OPENCLAW_REPO if source == "openclaw" else source
        skills_path = HERMES_SKILLS_PATH if source == "hermes" else OPENCLAW_SKILLS_PATH if source == "openclaw" else "main/skills"

        if "/" not in repo:
            repo = f"github/{repo}"

        url = f"{GITHUB_API}/repos/{repo}/contents/{skills_path}"
        if category:
            url += f"/{category}"

        imported = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    items = resp.json()
                    for item in items:
                        if item["type"] == "dir":
                            name = item["name"]
                            ok = await self._import_from_github(repo, skills_path, name, source)
                            if ok:
                                imported.append(name)
                else:
                    logger.warning(f"Failed to list skills from {source}: {resp.status_code}")
            except Exception as e:
                logger.warning(f"Failed to sync {source}: {e}")

        return imported

    def list_imported(self) -> list[dict]:
        imported = []
        for skill_dir in self.skills_dir.iterdir():
            if skill_dir.is_dir():
                manifest_path = skill_dir / "manifest.json"
                if manifest_path.exists():
                    try:
                        with open(manifest_path, "r") as f:
                            data = json.load(f)
                            if data.get("source") in ("hermes", "openclaw"):
                                imported.append(data)
                    except (json.JSONDecodeError, IOError):
                        pass
        return imported
