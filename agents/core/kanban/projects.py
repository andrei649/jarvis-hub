"""Nerva's scoped consumer view of the pinned Hermes project store."""

from __future__ import annotations

from agents.core.file_tools import FileScopeError

from .context import require_context
from .upstream import projects_db as db


def resolve_project(ref: str | None) -> tuple[str | None, str | None, str | None]:
    """Resolve an active project for a signed Kanban workspace proposal."""
    require_context()
    if not ref:
        return None, None, None
    try:
        with db.connect_closing() as conn:
            project = db.get_project(conn, ref)
            if project is None or project.archived:
                raise ValueError("unknown or archived project")
            primary = project.primary_path or next(
                (folder.path for folder in project.folders if folder.is_primary),
                project.folders[0].path if project.folders else None,
            )
            return project.id, project.name, primary
    except FileNotFoundError as exc:
        raise ValueError("unknown or archived project") from exc
    except FileScopeError as exc:
        raise PermissionError("project path is outside the current file scope") from exc


def list_projects(*, include_archived: bool = False) -> list[dict]:
    """The donor dashboard projection, read afresh from the durable scoped DB."""
    require_context()
    try:
        with db.connect_closing() as conn:
            return [project.to_dict() for project in db.list_projects(conn, include_archived=include_archived)]
    except FileNotFoundError:
        return []
    except FileScopeError as exc:
        raise PermissionError("project path is outside the current file scope") from exc
