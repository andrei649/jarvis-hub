"""H058 — the owner's ``commands.user_allowed_commands``, for suites that run a user-tier
command as a non-owner.

Since H058 the chat command plane fails closed: a non-owner runs ``/help`` and ``/whoami``
and nothing else until the owner allows more for that channel and scope. A suite that
exercises a user-tier handler *as a non-owner* states that precondition explicitly: the
policy is written through the real ``settings_db`` into a private store, and the real gate
reads it from there.
"""

from __future__ import annotations

import pytest


def private_store(monkeypatch, tmp_path) -> None:
    """A settings store of this test's own, in which the owner has set nothing yet."""
    from agents.core import settings_db

    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "h058-access-settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)


def allow_user_tier(monkeypatch, tmp_path, names=None, *, channel: str = "*") -> list[str]:
    """Let a non-owner on *channel* (``"*"``: any) run *names* — the default registry's
    whole user tier when None — in a DM and in a group. Returns the names allowed."""
    from agents.core import settings_db, slash_access
    from agents.core.commands import USER, build_default_registry

    private_store(monkeypatch, tmp_path)
    if names is None:
        names = [command.name for command in build_default_registry().commands() if command.tier == USER]
    listed = sorted(names)
    settings_db.put_category(slash_access.CATEGORY, {
        slash_access.KEY: {channel: {"dm": listed, "group": listed}}})
    return listed


@pytest.fixture
def user_tier_allowed(monkeypatch, tmp_path):
    """The owner allowed every non-owner the default registry's whole user tier."""
    return allow_user_tier(monkeypatch, tmp_path)
