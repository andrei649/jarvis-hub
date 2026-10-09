"""Explicit Nerva seams for upstream facilities outside the Kanban state port."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from agents.core.kanban.context import require_context

VALID_REASONING_EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max", "ultra")
KANBAN_WORKER_EXIT_TRAILER = ""


def normalize_profile_name(name: str) -> str:
    stripped = str(name).strip()
    if not stripped:
        raise ValueError("profile name cannot be empty")
    return stripped.lower()


def get_active_profile_name() -> str:
    return require_context().profile


def get_env(name: str, default: str | None = None) -> str | None:
    """Return only identities bound by Nerva's live Kanban scope.

    Unknown names, including worker claim locks and process environment values,
    have no ambient fallback.
    """
    context = require_context()
    values = {
        "HERMES_KANBAN_TASK": context.task_id,
        "HERMES_KANBAN_RUN_ID": str(context.run_id) if context.run_id is not None else None,
        "HERMES_KANBAN_BOARD": context.board,
        "HERMES_KANBAN_HOME": str(context.home),
        "HERMES_HOME": str(context.home),
        "HERMES_SESSION_ID": context.session_id,
        "HERMES_PROFILE": context.profile,
    }
    if name == "HERMES_KANBAN_DB":
        from .kanban_db import kanban_db_path
        return str(kanban_db_path())
    return values.get(name) or default


def get_toolset_names() -> tuple[str, ...]:
    # Static TOOLSETS keys from the pinned toolsets.py. Dynamic plugin names
    # remain a separate unresolved registry integration.
    return (
        "web", "search", "x_search", "vision", "video", "image_gen", "video_gen",
        "computer_use", "terminal", "skills", "browser", "cronjob", "file", "tts",
        "todo", "memory", "context_engine", "session_search", "connections",
        "project", "bot_room", "desktop_ui", "setup", "clarify", "code_execution",
        "delegation", "homeassistant", "kanban", "discord", "discord_admin",
        "yuanbao", "feishu_doc", "feishu_drive", "spotify", "debugging", "safe",
        "coding", "hermes-acp", "hermes-api-server", "hermes-cli", "hermes-cron",
        "hermes-telegram", "hermes-discord", "hermes-whatsapp", "hermes-slack",
        "hermes-signal", "hermes-bluebubbles", "hermes-homeassistant",
        "hermes-email", "hermes-mattermost", "hermes-matrix", "hermes-dingtalk",
        "hermes-feishu", "hermes-weixin", "hermes-qqbot", "hermes-wecom",
        "hermes-wecom-callback", "hermes-yuanbao", "hermes-sms",
        "hermes-webhook", "hermes-gateway",
    )


def require_scoped_path(path: Path | str) -> Path:
    root = require_context().home.expanduser().resolve()
    candidate = Path(path).expanduser().resolve()
    if not candidate.is_relative_to(root):
        raise PermissionError("Kanban path escapes its scoped Nerva data home")
    return candidate


def require_workspace_path(path: Path | str) -> Path:
    """Validate an artifact or workspace path through Nerva's file boundary."""
    require_context()
    from agents.core.file_tools import FileScope

    return FileScope.from_env().resolve(str(path))


def preflight_db_writability(path: Path, *, db_label: str = "kanban.db") -> None:
    """Refuse unwritable DBs or WAL sidecars within the scoped Nerva home."""
    path = require_scoped_path(path)
    for candidate in (path.parent, path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        if candidate.exists() and not os.access(candidate, os.R_OK | os.W_OK):
            raise sqlite3.OperationalError(f"{db_label} is not writable: {candidate}")


def unresolved(name: str):
    raise NotImplementedError(f"Kanban {name} requires an explicit Nerva integration")


def release_lsp_clients(*args, **kwargs):
    unresolved("workspace/LSP cleanup")


def _worktree_has_unpushed_commits(*args, **kwargs):
    unresolved("Git worktree inspection")


def _worktree_is_dirty(*args, **kwargs):
    unresolved("Git worktree inspection")
