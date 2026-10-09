"""Owner CLI's persistent board choice; worker scopes remain fixed."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from ..context import KanbanContext, kanban_scope, require_mutation
from ..upstream import kanban_db as kb
from ..upstream.compat import require_scoped_path


def selected_board(home: Path) -> str:
    root = Path(home).expanduser().resolve()
    pointer = root / "kanban" / "current"
    try:
        invalid = pointer.is_symlink() or not pointer.resolve().is_relative_to(root) or not pointer.is_file()
    except (OSError, RuntimeError):
        return kb.DEFAULT_BOARD
    if invalid:
        return kb.DEFAULT_BOARD
    try:
        slug = kb._require_slug(pointer.read_text(encoding="utf-8").strip())
    except (OSError, ValueError, UnicodeError):
        return kb.DEFAULT_BOARD
    with kanban_scope(KanbanContext(root, "board-selector")):
        return slug if kb.board_exists(slug) else kb.DEFAULT_BOARD


def select_board(slug: str) -> Path:
    context = require_mutation()
    if context.task_id is not None:
        raise PermissionError("workers cannot switch boards")
    normalized = kb._require_slug(slug)
    if not kb.board_exists(normalized):
        raise ValueError(f"board {normalized!r} does not exist")
    pointer = require_scoped_path(kb.current_board_path())
    pointer.parent.mkdir(parents=True, exist_ok=True)
    temp = require_scoped_path(pointer.with_name(f"current.{secrets.token_hex(8)}.tmp"))
    try:
        temp.write_text(normalized + "\n", encoding="utf-8")
        os.replace(temp, pointer)
    finally:
        temp.unlink(missing_ok=True)
    return pointer
