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

Every read goes through :class:`ConfinedFS` bound to the project root: a symlink anywhere
on the way, a hard-linked file, a secret-looking path and a file over 256 KiB are not there.
"""
from __future__ import annotations

import json
import os
import re
import stat
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
MAX_READ_BYTES = 256 * 1024


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
    """What the confined file system treats as absent: the file tools' secret-name rule."""
    from agents.core.file_tools import _has_secret_part

    return _has_secret_part(list(parts))


class ConfinedFS:
    """The file system the adopted recipe code sees (bound through ``verify_fs.bound``).

    Confined to one project root: a path is looked up component by component from the
    root with ``lstat``, and any symlink component, a ``..``, a path outside the root or
    a secret-looking component makes it absent. A file is read only when it is a regular
    file with one link (a hard link could name a file outside the root), opened with
    ``O_NOFOLLOW`` and at most :data:`MAX_READ_BYTES`. The only write is to a path in
    *writable*: its folders must be real folders, an existing file must be a regular
    file with one link, and it is opened ``O_NOFOLLOW`` so a link planted between the
    check and the open fails instead of being followed.
    """

    def __init__(self, root: Path, *, writable: tuple[Path, ...] = ()) -> None:
        self.root = Path(os.path.abspath(str(root)))
        self.writable = frozenset(Path(os.path.abspath(str(p))) for p in writable)

    def _parts(self, pure) -> tuple[str, ...] | None:
        path = Path(str(pure))
        if not path.is_absolute():
            return None
        try:
            rel = path.relative_to(self.root)
        except ValueError:
            return None
        parts = rel.parts
        if any(p in ("..", ".", "") for p in parts) or hidden_part(parts):
            return None
        return parts

    def _lstat(self, pure, *, leaf_must_exist: bool = True):
        """``(path, stat or None)`` with no symlink on the way, else None."""
        parts = self._parts(pure)
        if parts is None:
            return None
        here = self.root
        try:
            st = os.lstat(here)
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
                return None
            for index, part in enumerate(parts):
                here = here / part
                try:
                    st = os.lstat(here)
                except FileNotFoundError:
                    if leaf_must_exist or index != len(parts) - 1:
                        return None
                    return here, None
                if stat.S_ISLNK(st.st_mode):
                    return None
                if index != len(parts) - 1 and not stat.S_ISDIR(st.st_mode):
                    return None
        except OSError:
            return None
        return here, st

    def exists(self, pure) -> bool:
        return self._lstat(pure) is not None

    def is_file(self, pure) -> bool:
        found = self._lstat(pure)
        return found is not None and stat.S_ISREG(found[1].st_mode) and found[1].st_nlink == 1

    def is_dir(self, pure) -> bool:
        found = self._lstat(pure)
        return found is not None and stat.S_ISDIR(found[1].st_mode)

    def read_text(self, pure, encoding: str, errors: str) -> str:
        found = self._lstat(pure)
        if found is None:
            raise FileNotFoundError(str(pure))
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(found[0], flags)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                raise OSError(f"{found[0].name}: not a plain file")
            with os.fdopen(fd, "rb", closefd=False) as handle:
                data = handle.read(MAX_READ_BYTES + 1)
        finally:
            os.close(fd)
        if len(data) > MAX_READ_BYTES:
            raise OSError(f"{found[0].name}: larger than {MAX_READ_BYTES} bytes")
        return data.decode(encoding, errors)

    def write_text(self, pure, data: str, encoding: str, errors: str) -> int:
        target = Path(os.path.abspath(str(pure)))
        if target not in self.writable:
            raise PermissionError(f"{pure}: not a path the verify layer may write")
        found = self._lstat(pure, leaf_must_exist=False)
        if found is None:
            raise PermissionError(f"{pure}: a link or a missing folder on the way")
        path, st = found
        if st is not None and (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1):
            raise PermissionError(f"{pure}: not a plain file")
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags, 0o644)
        try:
            if os.fstat(fd).st_nlink != 1:
                raise PermissionError(f"{pure}: not a plain file")
            payload = data.encode(encoding, errors)
            os.write(fd, payload)
        finally:
            os.close(fd)
        return len(data)

    def mkdir(self, pure, exist_ok: bool) -> None:
        folder = Path(os.path.abspath(str(pure)))
        if not any(folder == w.parent for w in self.writable):
            raise PermissionError(f"{pure}: not a folder the verify layer may create")
        found = self._lstat(pure, leaf_must_exist=False)
        if found is None:
            raise PermissionError(f"{pure}: a link on the way")
        path, st = found
        if st is None:
            os.mkdir(path, 0o755)
        elif not stat.S_ISDIR(st.st_mode):
            raise PermissionError(f"{pure}: not a folder")
        elif not exist_ok:
            raise FileExistsError(str(pure))


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

    with bound(ConfinedFS(root)):
        try:
            return VPath(root, name).read_text(encoding="utf-8-sig", errors="replace")
        except (OSError, ValueError):
            return ""


def _is_file(root: Path, name: str) -> bool:
    from agents.vendor.hermes_compat.verify_fs import Path as VPath
    from agents.vendor.hermes_compat.verify_fs import bound

    with bound(ConfinedFS(root)):
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
    detection (``detected``), read through the confined file system."""
    from agents.vendor.hermes.agent.verify.environment import load_or_detect
    from agents.vendor.hermes_compat.verify_fs import Path as VPath
    from agents.vendor.hermes_compat.verify_fs import bound

    with bound(ConfinedFS(root)):
        return load_or_detect(VPath(root))


def detect_recipe(root: Path):
    """Fresh static detection only (``/verify detect``), ignoring a saved manifest."""
    from agents.vendor.hermes.agent.verify.recipes import detect_recipe as _detect
    from agents.vendor.hermes_compat.verify_fs import Path as VPath
    from agents.vendor.hermes_compat.verify_fs import bound

    with bound(ConfinedFS(root)):
        return _detect(VPath(root))


def save_recipe(root: Path, recipe) -> Path:
    """Write *recipe* to the project's ``.hermes/environment.json`` (upstream's own
    ``save_manifest``); that one file, reached with no link on the way, is the only
    path the confined file system lets it write."""
    from agents.vendor.hermes.agent.verify.environment import save_manifest
    from agents.vendor.hermes_compat.verify_fs import Path as VPath
    from agents.vendor.hermes_compat.verify_fs import bound

    target = manifest_path(root)
    with bound(ConfinedFS(root, writable=(target,))):
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
    "CONTEXT_FILES", "ConfinedFS", "MANIFEST_RELPATH", "PROJECT_MARKERS", "ProjectFacts", "VERIFY_TARGETS",
    "detect_facts", "detect_recipe", "facts_for", "file_scope", "load_recipe", "manifest_path",
    "save_recipe", "verify_commands", "workspace_root",
]
