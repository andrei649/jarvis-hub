"""
loader.py — Skill Pack loader & procedural memory system.
A skill pack is a directory with SKILL.md + optional Python modules.
Agents can generate new skills from successful task completions.
"""

import importlib.util
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from . import signing

logger = logging.getLogger("jarvis.skills")

SKILLS_DIR = Path("skills")


def _split_frontmatter(content: str) -> tuple[Optional[dict], str]:
    """Split a SKILL.md into (yaml_frontmatter_dict, body).

    Returns (None, content) when there is no parseable ``---`` frontmatter
    block, so callers can fall back to the Markdown-heading dialect.
    """
    if not content.startswith("---"):
        return None, content
    lines = content.split("\n")
    if lines[0].strip() != "---":
        return None, content
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            try:
                import yaml
                data = yaml.safe_load("\n".join(lines[1:i]))
            except Exception:
                return None, content
            body = "\n".join(lines[i + 1:])
            return (data, body) if isinstance(data, dict) else (None, content)
    return None, content


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

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "agents": self.agents,
            "trusted": self.trusted,
            "signature_reason": self.signature_reason,
            "sandboxed": self.sandboxed,
            "has_module": self.module is not None,
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

    def register_command(self, name: str, fn: Callable):
        self.commands[name] = fn

    async def execute(self, command: str, args: str = "", context: dict = None) -> str:
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
                logger.warning("Skill '%s' handle() raised for command '%s'", self.name, command, exc_info=True)
                return f"[skill:{self.name}] error: {e}"

        return ""

    def has_command(self, command: str) -> bool:
        if command in self.commands:
            return True
        if self.module and hasattr(self.module, "get_commands"):
            return command in self.module.get_commands()
        return False


class SkillLoader:
    def __init__(self):
        self.skills: dict[str, Skill] = {}

    def discover(self):
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        for skill_dir in sorted(SKILLS_DIR.iterdir()):
            if skill_dir.is_dir():
                self._load_skill(skill_dir)
        logger.info(f"Skills loaded: {list(self.skills.keys())}")
        return self.skills

    def _load_skill(self, path: Path):
        skill_file = path / "SKILL.md"
        if not skill_file.exists():
            return

        manifest = self._parse_manifest(skill_file)
        name = manifest.get("name", path.name)
        skill = Skill(name, path, manifest)

        # H12.1 — verify signature (advisory). Unsigned/invalid skills load but
        # are flagged untrusted; when JARVIS_REQUIRE_SIGNED_SKILLS=1 their Python
        # module is not exec'd in-process (sandboxed/flagged instead).
        skill.trusted, skill.signature_reason = signing.verify_skill(path)
        require_signed = signing.require_signed()

        py_file = path / "main.py"
        if py_file.exists() and require_signed and not skill.trusted:
            # Strict mode: refuse to exec untrusted code in-process. The skill is
            # flagged sandboxed; the HUD/executor can run it via the Sandbox.
            skill.sandboxed = True
            logger.warning(
                "Skill '%s' is %s and JARVIS_REQUIRE_SIGNED_SKILLS=1 — module NOT loaded "
                "in-process (flagged sandboxed)", name, skill.signature_reason,
            )
        elif py_file.exists():
            if not skill.trusted:
                logger.info(
                    "Skill '%s' is %s — loaded in advisory mode (flagged untrusted)",
                    name, skill.signature_reason,
                )
            try:
                spec = importlib.util.spec_from_file_location(f"skill_{name}", py_file)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    skill.module = mod
                    if hasattr(mod, "register"):
                        mod.register(skill)
                    if hasattr(mod, "get_commands"):
                        for cmd in mod.get_commands():
                            skill.register_command(cmd, getattr(mod, cmd))
                    logger.info(f"Loaded skill module: {name}")
            except Exception as e:
                logger.warning(f"Failed to load skill module {name}: {e}")

        self.skills[name] = skill
        logger.info(f"Loaded skill: {name} v{skill.version}")

    def _parse_manifest(self, path: Path) -> dict:
        content = path.read_text(encoding="utf-8")
        default_name = path.parent.name

        # SKILL.md comes in two dialects: our own Markdown-heading style
        # (# name / > desc / **Version:** …) and the agentskills.io / Hermes
        # YAML-frontmatter style (--- … ---). Detect frontmatter first; fall
        # back to the heading parser for everything else.
        fm, body = _split_frontmatter(content)
        if fm is not None:
            return self._manifest_from_frontmatter(fm, body, default_name)
        return self._manifest_from_headings(content, default_name)

    def _manifest_from_frontmatter(self, fm: dict, body: str, default_name: str) -> dict:
        meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
        hermes = meta.get("hermes") if isinstance(meta.get("hermes"), dict) else {}

        requires = fm.get("requires") or hermes.get("requires_toolsets") or []
        if isinstance(requires, str):
            requires = [r.strip() for r in requires.split(",") if r.strip()]
        agents = fm.get("agents") or []
        if isinstance(agents, str):
            agents = [a.strip() for a in agents.split(",") if a.strip()]
        commands = fm.get("commands") if isinstance(fm.get("commands"), list) else []
        if not commands:
            commands = self._parse_commands_from_body(body)

        return {
            "name": fm.get("name", default_name),
            "description": fm.get("description", ""),
            "version": str(fm.get("version", "0.1.0")),
            "author": fm.get("author", "unknown"),
            "license": fm.get("license", ""),
            "agents": list(agents),
            "requires": list(requires),
            "commands": commands,
        }

    def _manifest_from_headings(self, content: str, default_name: str) -> dict:
        manifest = {
            "name": default_name, "description": "",
            "version": "0.1.0", "agents": [],
            "requires": [], "commands": [],
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
                    manifest["commands"].append({
                        "command": match.group(1),
                        "args": match.group(2) or "",
                        "description": match.group(3),
                    })

        return manifest

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
                    commands.append({
                        "command": match.group(1),
                        "args": match.group(2) or "",
                        "description": match.group(3),
                    })
        return commands

    def parse_command(self, text: str) -> Optional[tuple[str, str, str]]:
        """Parse text for skill commands like 'weather bucuresti' or 'skill:weather bucuresti'."""
        text = text.strip().lower()

        skill_match = re.match(r"skill:(\w+)\s+(.+)$", text)
        if skill_match:
            return (skill_match.group(1), skill_match.group(1), skill_match.group(2))

        for name, skill in self.skills.items():
            for cmd_meta in skill.commands_meta:
                cmd_name = cmd_meta["command"]
                pattern = rf"^{cmd_name}\s+(.+)$"
                match = re.match(pattern, text)
                if match:
                    return (name, cmd_name, match.group(1))

        for name, skill in self.skills.items():
            for cmd_meta in skill.commands_meta:
                cmd_name = cmd_meta["command"]
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
        skill_dir = SKILLS_DIR / skill_name
        if skill_dir.exists():
            logger.info(f"Skill '{skill_name}' already exists, skipping generation")
            return None

        skill_dir.mkdir(parents=True, exist_ok=True)
        cmd = command_name or skill_name

        steps_text = "\n".join(f"{i+1}. {s}" for i, s in enumerate(solution_steps))

        skill_md = f"""# {skill_name.replace('_', ' ').title()}

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

        (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

        main_py = '''"""
$skill_name.py — Auto-generated skill from $agent_id
Generated: $timestamp
"""

import logging

logger = logging.getLogger("jarvis.skills.$skill_name")


async def handle(cmd: str, args: str, context: dict) -> str:
    """Handle skill invocation."""
    logger.info("Skill %s called with args: %s", cmd, args)
    return "[skill:$skill_name] executed — implement logic in handle()"


def get_commands() -> list[str]:
    return ["$cmd"]


def register(skill):
    """Register commands with the skill system."""
    skill.register_command("$cmd", handle)
'''
        main_py = (main_py
            .replace("$skill_name", skill_name)
            .replace("$agent_id", agent_id)
            .replace("$cmd", cmd)
            .replace("$timestamp", datetime.now(timezone.utc).isoformat())
        )
        (skill_dir / "main.py").write_text(main_py, encoding="utf-8")

        # H12.1 — self-sign locally generated skills so they load as trusted.
        signing.sign_skill(skill_dir)

        self._load_skill(skill_dir)
        logger.info(f"Generated new skill: {skill_name} from {agent_id}")
        return skill_name

    def sign_skill(self, name: str) -> Optional[str]:
        """Sign an already-discovered skill in place; re-verify it. (H12.1)"""
        skill = self.skills.get(name)
        if skill is None:
            return None
        line = signing.sign_skill(skill.path)
        skill.trusted, skill.signature_reason = signing.verify_skill(skill.path)
        return line

    def _name_from_task(self, task: str) -> str:
        words = re.sub(r"[^a-zA-Z0-9\s]", "", task).lower().split()
        important = [w for w in words if w not in ("the", "a", "an", "for", "to", "in", "of", "and", "is", "at")]
        if not important:
            important = ["custom"]
        name = "_".join(important[:4])
        timestamp = datetime.now(timezone.utc).strftime("%H%M%S")
        return f"{name}_{timestamp}"

    def get_skill(self, name: str) -> Optional[Skill]:
        return self.skills.get(name)

    def get_skills_for_agent(self, agent_id: str) -> list[Skill]:
        return [s for s in self.skills.values() if agent_id in s.agents or "all" in s.agents]
