"""The saved MCP reread requires an exact, expiring owner confirmation."""

from __future__ import annotations

import asyncio
import re
import threading
from types import SimpleNamespace

import pytest

from agents.core import mcp_reload_confirmation as confirmation
from agents.core.channels import outbound_safety
from agents.core.commands import Principal
from agents.core.maintenance_commands import _mcp_result_report, reload_mcp
from agents.core.mcp.client import MCPManager


@pytest.fixture(autouse=True)
def _clear_proposals():
    with confirmation._lock:
        confirmation._proposals.clear()
    yield
    with confirmation._lock:
        confirmation._proposals.clear()


def _ctx(manager, *, principal=None, args="", orch=None):
    if orch is None:
        orch = SimpleNamespace(mcp=manager)
    return SimpleNamespace(orch=orch, principal=principal or Principal(channel="web", admin=True), args=args)


def _saved(manager, state, *, held=None):
    return confirmation.SavedRead(
        list(state["rows"]), list(held or []), state["settings"], "boot", state["loadset"],
        id(manager.saved_reload_load_set),
    )


def _manager(monkeypatch, state, *, held=None):
    manager = MCPManager()
    manager.saved_reload_load_set = {"disabled": (), "only": ()}
    committed = []
    manager.saved_reload_commit_held = lambda rows: committed.append(rows)
    monkeypatch.setattr(manager, "_halted", lambda name=None: None)
    monkeypatch.setattr("agents.core.safe_mode.enabled", lambda: False)
    monkeypatch.setattr(confirmation, "_read_saved_config", lambda _manager: _saved(manager, state, held=held))

    def prepare(rows):
        return SimpleNamespace(fingerprint=str(state["plan"]),
                               summary={"added": len(rows), "changed": 0, "removed": 0,
                                        "unchanged": 0})

    monkeypatch.setattr(manager, "prepare_saved_reload", prepare)
    calls = []

    async def apply(_plan, *, still_current):
        calls.append("apply")
        assert await still_current()
        return {"status": "ok", "servers": {
            "docs": {"status": "added", "connected_after": False,
                     "added": [], "removed": [], "changed": []}}}

    monkeypatch.setattr(manager, "apply_saved_reload", apply)
    return manager, calls, committed


def _nonce(reply):
    match = re.search(r"/reload_mcp confirm ([A-Za-z0-9_-]+)", reply)
    assert match, reply
    return match.group(1)


@pytest.mark.asyncio
async def test_preview_confirm_is_single_use_and_only_commits_held_after_success(monkeypatch):
    state = {"rows": [{"name": "docs"}], "settings": "same", "loadset": "same", "plan": "same"}
    held = [{"name": "held", "command": "private-secret"}]
    manager, calls, committed = _manager(monkeypatch, state, held=held)
    orch = SimpleNamespace(mcp=manager)
    owner = Principal(channel="web", admin=True)
    preview = await reload_mcp(_ctx(manager, principal=owner, orch=orch))
    assert "private-secret" not in preview and "New servers stay disconnected" in preview
    assert not calls and not committed
    nonce = _nonce(preview)
    reply = await reload_mcp(_ctx(manager, principal=owner, args=f"confirm {nonce}", orch=orch))
    assert "applied" in reply.lower() and "docs" in reply and calls == ["apply"]
    assert committed == [held]
    replay = await reload_mcp(_ctx(manager, principal=owner, args=f"confirm {nonce}", orch=orch))
    assert "already used" in replay and calls == ["apply"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["settings", "loadset", "plan", "snapshot", "manager", "expiry"])
async def test_changed_exact_plan_or_authority_refuses_before_apply(monkeypatch, change):
    state = {"rows": [{"name": "docs"}], "settings": "same", "loadset": "same", "plan": "same"}
    manager, calls, committed = _manager(monkeypatch, state)
    orch = SimpleNamespace(mcp=manager)
    principal = Principal(channel="telegram", sender="owner-1", chat="chat-1", admin=True)
    now = [100.0]
    monkeypatch.setattr(confirmation.time, "monotonic", lambda: now[0])
    nonce = _nonce(await reload_mcp(_ctx(manager, principal=principal, orch=orch)))
    if change in state:
        state[change] = "changed"
    elif change == "snapshot":
        manager.saved_reload_load_set = {"disabled": (), "only": ()}
    elif change == "manager":
        orch.mcp = MCPManager()
    else:
        now[0] += confirmation.TTL_SECONDS + 1
    reply = await reload_mcp(_ctx(manager, principal=principal, args=f"confirm {nonce}", orch=orch))
    assert any(word in reply.lower() for word in ("changed", "invalid", "expired", "unavailable"))
    assert not calls and not committed


@pytest.mark.asyncio
async def test_wrong_actor_does_not_consume_owner_proposal_and_cancel_is_pending_only(monkeypatch):
    state = {"rows": [], "settings": "same", "loadset": "same", "plan": "same"}
    manager, calls, _committed = _manager(monkeypatch, state)
    orch = SimpleNamespace(mcp=manager)
    owner = Principal(channel="telegram", sender="one", chat="room", scope="group", admin=True)
    other = Principal(channel="telegram", sender="two", chat="room", scope="group", admin=True)
    nonce = _nonce(await reload_mcp(_ctx(manager, principal=owner, orch=orch)))
    wrong = await reload_mcp(_ctx(manager, principal=other, args=f"confirm {nonce}", orch=orch))
    assert "invalid" in wrong.lower() and not calls
    assert "pending" in (await reload_mcp(_ctx(manager, principal=owner, args="cancel", orch=orch))).lower()
    assert "invalid" in (await reload_mcp(_ctx(manager, principal=owner,
                                               args=f"confirm {nonce}", orch=orch))).lower()


@pytest.mark.asyncio
async def test_settings_read_is_off_loop_and_cancel_waits_for_reader(monkeypatch):
    state = {"rows": [], "settings": "same", "loadset": "same", "plan": "same"}
    manager, _calls, _committed = _manager(monkeypatch, state)
    entered, release = threading.Event(), threading.Event()
    main_thread = threading.get_ident()

    def read(_manager):
        assert threading.get_ident() != main_thread
        entered.set()
        assert release.wait(3)
        return _saved(manager, state)

    monkeypatch.setattr(confirmation, "_read_saved_config", read)
    task = asyncio.create_task(reload_mcp(_ctx(manager)))
    assert await asyncio.to_thread(entered.wait, 2)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not confirmation._proposals


@pytest.mark.asyncio
async def test_apply_rechecks_config_and_does_not_commit_held_on_partial(monkeypatch):
    state = {"rows": [{"name": "docs"}], "settings": "same", "loadset": "same", "plan": "same"}
    manager, calls, committed = _manager(monkeypatch, state, held=[{"name": "secret"}])
    orch = SimpleNamespace(mcp=manager)

    async def apply(_plan, *, still_current):
        calls.append("apply")
        assert await still_current()
        state["settings"] = "changed-during-apply"
        assert not await still_current()
        return {"status": "partial", "servers": {
            "docs": {"status": "failed_retained", "connected_after": False,
                     "added": [], "removed": [], "changed": []}}}

    monkeypatch.setattr(manager, "apply_saved_reload", apply)
    nonce = _nonce(await reload_mcp(_ctx(manager, orch=orch)))
    reply = await reload_mcp(_ctx(manager, args=f"confirm {nonce}", orch=orch))
    assert "partial" in reply.lower() and calls == ["apply"] and not committed


def test_strict_saved_read_uses_boot_load_set_and_rejects_duplicate_held_rows(monkeypatch):
    manager = MCPManager()
    manager.saved_reload_load_set = {"disabled": ("held",), "only": ()}
    monkeypatch.setattr(confirmation.settings_db, "ensure_initialized", lambda: None)
    monkeypatch.setattr(confirmation.settings_db, "_require_readable_store", lambda: None)
    rows = [{"name": "live", "command": "one"}, {"name": "held", "command": "private"}]

    def category(name):
        if name == "mcp":
            return [{"key": "servers", "value": rows}]
        return [{"key": "mcp_disabled", "value": ""}, {"key": "mcp_only", "value": ""}]

    monkeypatch.setattr(confirmation.settings_db, "get_category", category)
    read = confirmation._read_saved_config(manager)
    assert [row["name"] for row in read.allowed_rows] == ["live"]
    assert [row["name"] for row in read.held_rows] == ["held"]
    assert "private" not in repr(confirmation.Proposal(
        ("web", None, None, "dm"), __import__("weakref").ref(manager), "n", "f",
        read.settings_digest, read.boot_digest, read.live_loadset_digest, read.snapshot_id, 1.0))
    rows.append({"name": "held", "command": "another"})
    with pytest.raises(confirmation.SavedConfigUnavailable):
        confirmation._read_saved_config(manager)


@pytest.mark.asyncio
async def test_missing_boot_snapshot_refuses_preview(monkeypatch):
    manager = MCPManager()
    manager.saved_reload_commit_held = lambda _rows: None
    monkeypatch.setattr(manager, "_halted", lambda name=None: None)
    monkeypatch.setattr("agents.core.safe_mode.enabled", lambda: False)
    monkeypatch.setattr(confirmation.settings_db, "ensure_initialized", lambda: None)
    monkeypatch.setattr(confirmation.settings_db, "_require_readable_store", lambda: None)
    reply = await reload_mcp(_ctx(manager))
    assert "unreadable" in reply.lower() and "confirm" not in reply.lower()


@pytest.mark.asyncio
async def test_real_manager_adds_saved_server_disconnected_without_starting_it(monkeypatch):
    manager = MCPManager()
    manager.saved_reload_load_set = {"disabled": (), "only": ()}
    committed = []
    manager.saved_reload_commit_held = lambda rows: committed.append(rows)
    monkeypatch.setattr("agents.core.safe_mode.enabled", lambda: False)
    monkeypatch.setattr(manager, "_halted", lambda name=None: None)
    row = {"name": "docs", "command": "never-run-this-command"}
    state = {"rows": [row], "settings": "stable", "loadset": "stable"}
    monkeypatch.setattr(confirmation, "_read_saved_config", lambda _manager: _saved(manager, state))
    orch = SimpleNamespace(mcp=manager)

    nonce = _nonce(await reload_mcp(_ctx(manager, orch=orch)))
    reply = await reload_mcp(_ctx(manager, args=f"confirm {nonce}", orch=orch))

    assert "applied" in reply.lower()
    assert manager.servers["docs"].wanted is False
    assert not manager.servers["docs"].is_connected()
    assert committed == [[]]


def test_actual_diff_report_sanitizes_long_known_secret_before_clipping(monkeypatch):
    secret = "private" * 20
    monkeypatch.setattr(outbound_safety, "_known_redactor",
                        lambda text: text.replace(secret, "[REDACTED]"))
    report = _mcp_result_report({"status": "ok", "servers": {
        "docs": {"status": "added", "connected_after": False,
                 "added": [secret + " tool"], "removed": [], "changed": []},
    }})
    assert secret not in report
    assert secret[:40] not in report
    assert "[REDACTED]" in report
