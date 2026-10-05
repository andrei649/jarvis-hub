"""Closed-lifetime cwd/file binding for one controller-owned board execution."""

from __future__ import annotations

import stat
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from agents.core.file_tools import FileScope, FileScopeError, FileTools

from .context import KanbanContext, current_context


@dataclass(eq=False)
class WorkspaceBinding:
    context: KanbanContext
    cwd: Path
    project_root: Path | None
    still_current: Callable[[], bool]
    identity: tuple[int, int]
    closed: bool = False

    def check(self) -> None:
        context = current_context()
        if (self.closed or context is not self.context or not context.can_mutate
                or context.delegated or not context.task_id
                or type(context.run_id) is not int or context.run_id <= 0):
            raise FileScopeError("outside_scope")
        try:
            if self.still_current() is not True:
                raise FileScopeError("outside_scope")
            _admitted_cwd(context, self.cwd)
            info = self.cwd.stat(follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != self.identity:
                raise FileScopeError("outside_scope")
        except (OSError, RuntimeError, ValueError) as exc:
            raise FileScopeError("outside_scope") from exc
        except Exception as exc:
            # A failed proof never falls back to the owner's ambient file roots.
            raise FileScopeError("outside_scope") from exc

    def file_scope(self) -> FileScope:
        self.check()
        return _WorkspaceFileScope(self)


def _admitted_cwd(context: KanbanContext, cwd: Path) -> None:
    if not cwd.is_absolute() or cwd.resolve(strict=True) != cwd or cwd.is_symlink():
        raise FileScopeError("outside_scope")
    from .upstream import kanban_db as kb

    managed = kb.workspaces_root(board=context.board).resolve() / context.task_id
    if cwd != managed:
        FileScope.from_env().resolve(str(cwd))


class _WorkspaceFileScope(FileScope):
    def __init__(self, binding: WorkspaceBinding):
        self.binding = binding
        super().__init__([binding.cwd])

    @property
    def roots(self):
        self.binding.check()
        return super().roots

    def root_for(self, path):
        self.binding.check()
        return super().root_for(path)

    def resolve(self, path):
        self.binding.check()
        return super().resolve(path)


_CURRENT: ContextVar[WorkspaceBinding | None] = ContextVar("nerva_kanban_workspace", default=None)
_LIFECYCLE_LOCK = threading.RLock()
_LIVE_BINDINGS: set[WorkspaceBinding] = set()


def current_workspace() -> WorkspaceBinding | None:
    binding = _CURRENT.get()
    if binding is not None:
        binding.check()
    return binding


def _lifecycle_is_bound(task_id: str, path: str | Path | None = None) -> bool:
    context = current_context()
    if context is None:
        return False
    return any(not binding.closed and (
        (binding.context.home == context.home and binding.context.board == context.board
         and binding.context.task_id == task_id)
        or (path is not None and binding.cwd == Path(path))
    ) for binding in _LIVE_BINDINGS)


def workspace_lifecycle_is_bound(task_id: str, *, path: str | Path | None = None) -> bool:
    """Defer cleanup until the bound runner exits, including after completion.

    This is only a cleanup-deferral predicate: it grants no filesystem effect
    and deliberately remains true after a terminal transition closes tool access.
    """
    with _LIFECYCLE_LOCK:
        return _lifecycle_is_bound(task_id, path)


@contextmanager
def workspace_reclamation_guard(task_id: str, path: Path) -> Iterator[bool]:
    """Serialize the last cleanup check/removal against new runner bindings."""
    with _LIFECYCLE_LOCK:
        yield not _lifecycle_is_bound(task_id, path)


@contextmanager
def workspace_scope(cwd: Path, *, still_current: Callable[[], bool],
                    project_root: Path | None = None) -> Iterator[WorkspaceBinding]:
    context = current_context()
    if (context is None or not context.can_mutate or context.delegated
            or not context.task_id or type(context.run_id) is not int or context.run_id <= 0
            or not callable(still_current)):
        raise FileScopeError("outside_scope")
    cwd = Path(cwd)
    _admitted_cwd(context, cwd)
    info = cwd.stat(follow_symlinks=False)
    binding = WorkspaceBinding(context, cwd, project_root, still_current, (info.st_dev, info.st_ino))
    with _LIFECYCLE_LOCK:
        binding.check()
        token = _CURRENT.set(binding)
        _LIVE_BINDINGS.add(binding)
    try:
        yield binding
    finally:
        with _LIFECYCLE_LOCK:
            binding.closed = True
            _LIVE_BINDINGS.discard(binding)
            _CURRENT.reset(token)


class _WorkerFileTools(FileTools):
    def __init__(self, base: FileTools, binding: WorkspaceBinding):
        self.binding = binding
        super().__init__(binding.file_scope(), snapshots=base.snapshots, max_bytes=base.max_bytes,
                         authorizer=base._authorizer, audit=base._audit,
                         agent=binding.context.profile, spill_dirs=base._spill_dirs)

    def _resolve_read(self, raw_path):
        self.binding.check()
        return super()._resolve_read(raw_path)

    def _spill_file(self, raw_path):
        self.binding.check()
        return super()._spill_file(raw_path)


def file_tools_for_workspace(base: FileTools) -> FileTools:
    """Select a fresh scoped handler without mutating the shared instance/history."""
    binding = current_workspace()
    return _WorkerFileTools(base, binding) if binding is not None else base
