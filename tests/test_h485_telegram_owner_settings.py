"""Persisted Telegram owner identity is independent of ingress admission."""

import sqlite3
import time
from types import SimpleNamespace

import pytest

from agents.core import settings_db
from agents.core.autonomy.queue import TaskQueue
from agents.core.autonomy.worker import AutonomyWorker
from agents.core.autonomy_coordinator import AutonomyCoordinator
from agents.core.channels.manager import ChannelManager
from agents.core.orchestrator import Orchestrator


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTONOMY_OWNER_CHAT_ID", raising=False)
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    return settings_db


async def test_saved_owner_ids_reload_and_revoke_without_closing_guest_admission(store, tmp_path):
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    try:
        worker = AutonomyWorker(queue)
        channel = SimpleNamespace(name="telegram", allowed_users=[])
        orch = Orchestrator.__new__(Orchestrator)
        orch.channel_manager = ChannelManager()
        orch.channels = {"telegram": channel}
        orch.autonomy, orch.autonomy_queue = worker, queue
        coordinator = AutonomyCoordinator(orch)
        orch.load_runtime_settings()
        assert orch.get_setting("autonomy.owner_user_ids") is None
        updated, skipped = store.put_category("autonomy", {"owner_chat_id": "-500", "owner_user_ids": [42]})
        assert (updated, skipped) == (2, [])
        orch.load_runtime_settings()
        assert orch.get_setting("autonomy.owner_user_ids") == [42]
        assert orch._channel_principal("telegram", "42", -500).admin
        assert not orch._channel_principal("telegram", "7", -500).admin
        task = await worker.submit("jarvis", "delete_file", "Delete test file", attention_mode="none")
        assert await coordinator._on_callback(task.id, "reject", chat_id=-500, user_id=7) is None
        assert queue.get(task.id).human_decision is None
        assert await coordinator._on_callback(task.id, "reject", chat_id=-500, user_id=42)
        assert queue.get(task.id).human_decision is not None
        assert store.put_category("autonomy", {"owner_user_ids": []}) == (1, [])
        # Persisted revocation must apply before the ordinary 30-second watcher.
        assert orch.get_setting("autonomy.owner_user_ids") == [42]
        assert not orch._channel_principal("telegram", "42", -500).admin
        pending = await worker.submit("jarvis", "delete_file", "Next test file", attention_mode="none")
        assert await coordinator._on_callback(pending.id, "reject", chat_id=-500, user_id=42) is None
        assert queue.get(pending.id).human_decision is None
        assert channel.allowed_users == []
    finally:
        queue.close()


@pytest.mark.parametrize("changed", [{"owner_chat_id": ""}, {"owner_user_ids": []}])
async def test_persisted_owner_revocation_refuses_a_stale_cached_callback(store, tmp_path, changed):
    queue = TaskQueue(str(tmp_path / "tasks.db")).initialize()
    try:
        orch = Orchestrator.__new__(Orchestrator)
        orch.channel_manager = ChannelManager()
        orch.channels = {"telegram": SimpleNamespace(name="telegram", allowed_users=[])}
        orch.autonomy, orch.autonomy_queue = AutonomyWorker(queue), queue
        store.put_category("autonomy", {"owner_chat_id": "-500", "owner_user_ids": [42]})
        orch.load_runtime_settings()
        coordinator = AutonomyCoordinator(orch)
        task = await orch.autonomy.submit("jarvis", "delete_file", "Synthetic pending test", attention_mode="none")
        store.put_category("autonomy", changed)
        assert orch.get_setting("autonomy.owner_chat_id") == "-500"
        assert orch.get_setting("autonomy.owner_user_ids") == [42]
        assert await coordinator._on_callback(task.id, "reject", chat_id=-500, user_id=42) is None
        assert queue.get(task.id).human_decision is None
    finally:
        queue.close()


def test_unreadable_owner_store_never_inherits_stale_or_environment_authority(store, monkeypatch):
    orch = Orchestrator.__new__(Orchestrator)
    orch.channel_manager = ChannelManager()
    orch.channels = {"telegram": SimpleNamespace(name="telegram", allowed_users=[42])}
    store.put_category("autonomy", {"owner_chat_id": "42", "owner_user_ids": [42]})
    orch.load_runtime_settings()
    monkeypatch.setenv("AUTONOMY_OWNER_CHAT_ID", "42")

    def unreadable(*args, **kwargs):
        raise OSError("synthetic settings read failure")

    monkeypatch.setattr(store, "read_telegram_owner_binding", unreadable)
    assert not orch._channel_principal("telegram", "42", 42).admin
    assert not AutonomyCoordinator(orch)._callback_is_owner(42, 42)


def test_locked_owner_store_refuses_without_blocking_the_chat_loop(store):
    store.put_category("autonomy", {"owner_chat_id": "42", "owner_user_ids": [42]})
    lock = sqlite3.connect(store.DB_PATH)
    lock.execute("PRAGMA journal_mode=DELETE")
    lock.execute("BEGIN EXCLUSIVE")
    try:
        orch = Orchestrator.__new__(Orchestrator)
        orch.channel_manager = ChannelManager()
        orch.channels = {"telegram": SimpleNamespace(name="telegram", allowed_users=[42])}
        started = time.monotonic()
        assert not orch._channel_principal("telegram", "42", 42).admin
        assert time.monotonic() - started < 1.0
    finally:
        lock.rollback()
        lock.close()
