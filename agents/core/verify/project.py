"""Which project a path is in, what its verify commands are, and its run recipe.

* **Workspace root.** The nearest folder at or above the path holding ``.git``, else the
  nearest (at most six levels up) holding a project manifest (Hermes's list:
  ``pyproject.toml``, ``package.json``, ``go.mod`` …). Never above the owner's file root
  the path sits in, and a path outside every root has no project.
* **Project facts** (Hermes ``coding_context.detect_project_facts``, re-written for
  Nerva): the manifests present, the package managers their lockfiles name, and the
  verify commands a person would type — ``<pm> run <script>`` for the package.json
  scripts named test, lint, typecheck, check, build, fmt or format; ``pytest`` when the
  project configures it; ``make <target>`` for those targets; ``scripts/run_tests.sh``.
  Only names from that closed list become commands, so a script's body never reaches a
  prompt.
* **Recipe** (Hermes ``detect_recipe`` / ``load_or_detect``, adopted): bootstrap, build and
  test commands, the start command and port. A saved ``.hermes/environment.json`` wins.

Every read goes through the confined path stand-in bound to the project root, so a
symlink out of the root, a secret-looking file and a file over 256 KiB are not there.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

#: Project-root signals (Hermes ``_PROJECT_MARKERS``, plus ``manage.py`` and the compose files
#: the adopted recipe detection itself recognises, so every detectable project has a root).
PROJECT_MARKERS = (
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "package.json", "tsconfig.json", "deno.json",
    "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts", "Gemfile", "composer.json", "mix.exs",
    "pubspec.yaml", "CMakeLists.txt", "Makefile", "Dockerfile", "AGENTS.md", "CLAUDE.md", ".cursorrules",
    "manage.py", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
)
CONTEXT_FILES = ("AGENTS.md", "CLAUDE.md", ".cursorrules")
_PY_LOCKFILES = (("uv.lock", "uv"), ("poetry.lock", "poetry"), ("Pipfile.lock", "pipenv"))
_JS_LOCKFILES = (
    ("pnpm-lock.yaml", "pnpm"), ("bun.lockb", "bun"), ("bun.lock", "bun"), ("yarn.lock", "yarn"),
    ("package-lock.json", "npm"),
)
#: package.json scripts / Makefile targets that become verify commands (Hermes ``_VERIFY_TARGETS``).
VERIFY_TARGETS = ("test", "tests", "lint", "typecheck", "check", "build", "fmt", "format")
MAX_VERIFY_COMMANDS = 8
MARKER_DEPTH = 6
MANIFEST_RELPATH = (".hermes", "environment.json")


@dataclass(frozen=True)
class ProjectFacts:
    root: str
    git: bool
    manifests: list[str] = field(default_factory=list)
    package_managers: list[str] = field(default_factory=list)
    verify_commands: list[str] = field(default_factory=list)
    context_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def hidden_part(parts: tuple[str, ...]) -> bool:
    """What the confined stand-in treats as absent: the file tools' secret-name rule."""
    from agents.core.file_tools import _has_secret_part

    return _has_secret_part(list(parts))


def file_scope():
    from agents.core.file_tools import FileScope

    return FileScope.from_env()


def _admit(path: object, scope) -> Path | None:
    """*path* resolved inside the owner's file roots (a folder: itself; a file: its folder)."""
    from agents.core.file_tools import FileScopeError

    try:
        target = scope.resolve(str(path))
    except (FileScopeError, OSError, TypeError):
        return None
    try:
        return target if target.is_dir() else target.parent
    except OSError:
        return None


def workspace_root(path: object, scope=None) -> tuple[Path, bool] | None:
    """``(root, is_git)`` for the project *path* is in, or None. Git root first, then the
    nearest marker folder; never above the file root *path* sits in."""
    scope = scope or file_scope()
    folder = _admit(path, scope)
    if folder is None:
        return None
    floor = scope.root_for(folder)
    if floor is None:
        return None
    chain = [folder, *[p for p in folder.parents if p == floor or floor in p.parents]]
    for here in chain:
        if (here / ".git").exists():
            return here, True
    for here in chain[: MARKER_DEPTH + 1]:
        if any((here / marker).exists() for marker in PROJECT_MARKERS):
            return here, False
    return None


def _read_small(root: Path, name: str) -> str:
    from agents.vendor.hermes_compat.verify_fs import Path as VPath
    from agents.vendor.hermes_compat.verify_fs import bound

    with bound(root, hidden=hidden_part):
        try:
            return VPath(root, name).read_text(encoding="utf-8-sig", errors="replace")
        except (OSError, ValueError):
            return ""


def _is_file(root: Path, name: str) -> bool:
    from agents.vendor.hermes_compat.verify_fs import Path as VPath
    from agents.vendor.hermes_compat.verify_fs import bound

    with bound(root, hidden=hidden_part):
        return VPath(root, name).is_file()


def detect_facts(root: Path, *, git: bool = False) -> ProjectFacts:
    """The project facts for *root* (an admitted workspace root)."""
    verify: list[str] = []
    if _is_file(root, "scripts/run_tests.sh"):
        verify.append("scripts/run_tests.sh")
    if _is_file(root, "package.json"):
        try:
            parsed = json.loads(_read_small(root, "package.json") or "{}")
            scripts = parsed.get("scripts") if isinstance(parsed, dict) else None
        except ValueError:
            scripts = None
        scripts = scripts if isinstance(scripts, dict) else {}
        js_pm = next((pm for lock, pm in _JS_LOCKFILES if _is_file(root, lock)), "npm")
        verify.extend(f"{js_pm} run {name}" for name in VERIFY_TARGETS if name in scripts)
    if _is_file(root, "pytest.ini") or "[tool.pytest" in _read_small(root, "pyproject.toml"):
        verify.append("pytest")
    makefile = _read_small(root, "Makefile")
    verify.extend(
        f"make {name}" for name in VERIFY_TARGETS
        if makefile and re.search(rf"^{re.escape(name)}\s*:", makefile, re.MULTILINE)
    )
    return ProjectFacts(
        root=str(root), git=git,
        manifests=[m for m in PROJECT_MARKERS if m not in CONTEXT_FILES and _is_file(root, m)],
        package_managers=list(dict.fromkeys(
            pm for lock, pm in (*_PY_LOCKFILES, *_JS_LOCKFILES) if _is_file(root, lock))),
        verify_commands=list(dict.fromkeys(verify))[:MAX_VERIFY_COMMANDS],
        context_files=[c for c in CONTEXT_FILES if _is_file(root, c)],
    )


def facts_for(path: object, scope=None) -> ProjectFacts | None:
    found = workspace_root(path, scope)
    if found is None:
        return None
    root, git = found
    return detect_facts(root, git=git)


def manifest_path(root: Path) -> Path:
    return Path(root).joinpath(*MANIFEST_RELPATH)


def load_recipe(root: Path):
    """``(Recipe | None, source)`` — the saved manifest (``manifest``) or fresh static
    detection (``detected``), read through the confined stand-in."""
    from agents.vendor.hermes.agent.verify.environment import load_or_detect
    from agents.vendor.hermes_compat.verify_fs import Path as VPath
    from agents.vendor.hermes_compat.verify_fs import bound

    with bound(root, hidden=hidden_part):
        return load_or_detect(VPath(root))


def detect_recipe(root: Path):
    """Fresh static detection only (``/verify detect``), ignoring a saved manifest."""
    from agents.vendor.hermes.agent.verify.recipes import detect_recipe as _detect
    from agents.vendor.hermes_compat.verify_fs import Path as VPath
    from agents.vendor.hermes_compat.verify_fs import bound

    with bound(root, hidden=hidden_part):
        return _detect(VPath(root))


def save_recipe(root: Path, recipe) -> Path:
    """Write *recipe* to the project's ``.hermes/environment.json`` (upstream's own
    ``save_manifest``); that one file is the only path the stand-in lets it write."""
    from agents.vendor.hermes.agent.verify.environment import save_manifest
    from agents.vendor.hermes_compat.verify_fs import Path as VPath
    from agents.vendor.hermes_compat.verify_fs import bound

    target = manifest_path(root)
    with bound(root, writable=(target,), hidden=hidden_part):
        written = save_manifest(VPath(root), recipe)
    return Path(str(written))


def verify_commands(facts: ProjectFacts, recipe=None) -> list[str]:
    """The commands whose passing run counts as evidence: the facts' verify commands and
    the recipe's build and test commands (Hermes merges the two the same way)."""
    commands = list(facts.verify_commands)
    if recipe is not None:
        commands.extend(getattr(recipe, "test", []) or [])
        commands.extend(getattr(recipe, "build", []) or [])
    return list(dict.fromkeys(c for c in commands if isinstance(c, str) and c.strip()))


__all__ = [
    "CONTEXT_FILES", "MANIFEST_RELPATH", "PROJECT_MARKERS", "ProjectFacts", "VERIFY_TARGETS",
    "detect_facts", "detect_recipe", "facts_for", "file_scope", "load_recipe", "manifest_path",
    "save_recipe", "verify_commands", "workspace_root",
]
