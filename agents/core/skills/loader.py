"""
loader.py — Skill Pack loader & procedural memory system.
A skill pack is a directory with SKILL.md + optional Python modules.
Agents can generate new skills from successful task completions.
"""

import importlib.util
import keyword
import logging
import re
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

from . import signing

logger = logging.getLogger("jarvis.skills")

# Anchored on the app root (repo checkout in dev, PyInstaller bundle when
# frozen) instead of the CWD, so skill discovery works no matter where the
# process was launched from. From the repo root this is the same "skills/"
# directory as before.
from agents.core.paths import app_root as _app_root  # noqa: E402

SKILLS_DIR = _app_root() / "skills"


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
    return bool(name and name not in (".", "..")
                and "/" not in name and "\\" not in name and "\x00" not in name)


def _skill_generation_contract_template() -> ContractTemplate:
    return ContractTemplate(
        kind="skill.generation",
        description="LLM-authored skill creation and owner-promotion gate.",
        constraints=(
            field_present("action", "agent"),
            one_of("action", {"generate", "approve"}),
            predicate("generated_skill_name_safe", _generated_skill_name_safe,
                      reason="invalid_skill_name"),
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
        # H20.5 — best-effort usage-telemetry hook (set by SkillLoader.attach_usage);
        # None keeps execute() byte-identical to today's behavior.
        self.usage_hook: Optional[Callable] = None

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
                logger.warning("Skill '%s' handle() raised for command '%s'", self.name, command, exc_info=True)
                return f"[skill:{self.name}] error: {e}"

        return ""


class SkillLoader:
    def __init__(self):
        self.skills: dict[str, Skill] = {}
        # H20.5 — optional usage-telemetry sidecar (SkillUsageStore); attached by
        # the orchestrator. None → zero behavior change.
        self._usage = None

    def attach_usage(self, store) -> None:
        """Attach a SkillUsageStore; hooks existing and future skills."""
        self._usage = store

        def _hook(name: str, kind: str) -> None:
            store.bump(name, kind)

        for skill in self.skills.values():
            skill.usage_hook = _hook

    def discover(self):
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        roots = [SKILLS_DIR]
        # The owner's personal skills (Documents/Jarvis/skills) load AFTER the
        # bundled tree so a same-named user skill wins the registry slot.
        user_dir = _user_skills_dir()
        if user_dir is not None and user_dir.is_dir() and user_dir.resolve() != SKILLS_DIR.resolve():
            roots.append(user_dir)
        for root in roots:
            for skill_dir in sorted(root.iterdir()):
                if skill_dir.is_dir():
                    self._load_skill(skill_dir)
        logger.info(f"Skills loaded: {list(self.skills.keys())}")
        return self.skills

    def _load_skill(self, path: Path):
        # H32.5: acquired packages are signed for integrity but are NEVER trusted
        # for in-process import. Their only execution path is the acquired Docker/
        # WASM runner registered through ToolRPC.
        if (path / "ACQUIRED_SANDBOX_ONLY").exists():
            logger.warning("Refused in-process discovery of sandbox-only acquired package")
            return
        skill_file = path / "SKILL.md"
        if not skill_file.exists():
            return

        manifest = self._parse_manifest(skill_file)
        name = manifest.get("name", path.name)
        skill = Skill(name, path, manifest)
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
            self.skills[name] = skill
            logger.info("Skill '%s' is PENDING REVIEW — NOT loaded in-process (quarantined)", name)
            return

        # H12.1 — verify signature (advisory). Unsigned/invalid skills load but
        # are flagged untrusted; when JARVIS_REQUIRE_SIGNED_SKILLS=1 their Python
        # module is not exec'd in-process (sandboxed/flagged instead).
        skill.trusted, skill.signature_reason = signing.verify_skill(path)
        # SEC-B2: raises when enforcement is on with no signing key — a gate that cannot
        # tell an attacker's signature from ours must stop the load rather than wave it
        # through. Deliberately NOT caught here: the operator has to see it.
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
        commands = self._normalize_commands(fm.get("commands"))
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
        for entry in raw:
            if isinstance(entry, dict):
                cmd = entry.get("command")
                if isinstance(cmd, str) and re.fullmatch(r"\w+", cmd):
                    out.append(entry)
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

        if not _skill_generation_allowed({
            "kind": SKILL_GENERATION_CONTRACT_KIND,
            "action": "generate",
            "agent": agent_id,
            "name": skill_name,
            "command_name": cmd,
            "steps_count": len(solution_steps or []),
            "has_output": bool(output),
        }):
            return None

        # CDX-8: the [learn:…] task/steps/command are UNTRUSTED LLM output (an injected
        # response could mint an attacker-named, attacker-described skill). Scan before we
        # create anything; never write injection-flagged content to disk as a skill.
        from ..security import quarantine
        flags = quarantine.detect_injection(" ".join([task_description, *solution_steps, str(cmd)]))
        if flags:
            logger.warning("Skill generation blocked — injection-flagged content from %s: %s",
                           agent_id, flags)
            return None

        # The scanner above has now seen the raw command name; from here on the value is
        # written to disk (as a `def` and as a SKILL.md command token), so it must be a
        # bare identifier.
        cmd = _safe_command_name(cmd, skill_name)

        skill_dir.mkdir(parents=True, exist_ok=True)

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
        main_py = (main_py
            .replace("$skill_name", skill_name)
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
            f"generated={datetime.now(timezone.utc).isoformat()}\n", encoding="utf-8")
        self._load_skill(skill_dir)
        # H20.5 — provenance: agent-created skills are the only curatable ones.
        # Record under the REGISTERED name (the manifest title, which is what
        # loader.skills is keyed by and what the curator iterates), not the
        # on-disk slug — they differ (`# {slug.title()}` heading).
        if self._usage is not None:
            try:
                registered = next(
                    (n for n, s in self.skills.items()
                     if Path(getattr(s, "path", "")) == skill_dir), skill_name)
                self._usage.note_created(registered, "agent")
            except Exception:
                logger.debug("usage provenance note skipped", exc_info=True)
        logger.info("Generated skill '%s' from %s — quarantined PENDING REVIEW (not active)",
                    skill_name, agent_id)
        return skill_name

    def approve_generated_skill(self, name: str) -> bool:
        """CDX-8: owner-approve a quarantined auto-generated skill — sign it, clear the
        PENDING_REVIEW marker, and load it in-process. Returns True if a pending skill was
        promoted, False if there was no such pending skill (idempotent / safe)."""
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
            skill_dir = next((c for c in candidates if (c / "PENDING_REVIEW").exists()),
                             candidates[0])
        if not (skill_dir / "PENDING_REVIEW").exists():
            return False
        if not _skill_generation_allowed({
            "kind": SKILL_GENERATION_CONTRACT_KIND,
            "action": "approve",
            "agent": "owner",
            "name": skill_dir.name,
            "command_name": name,
        }):
            return False
        signing.sign_skill(skill_dir)
        (skill_dir / "PENDING_REVIEW").unlink()
        self._load_skill(skill_dir)
        logger.info("Generated skill '%s' approved + activated", name)
        return True

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
