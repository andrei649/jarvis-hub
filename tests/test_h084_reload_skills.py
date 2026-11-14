"""H084: owner chat reloads skills with a truthful, staged registry diff."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import load_set, maintenance_commands, settings_db
from agents.core.commands import CommandRegistry, Principal, build_default_registry
from agents.core.skills import loader as loader_mod
from agents.core.skills.approval import SkillApprovalStore
from agents.core.skills.loader import SkillLoader
from agents.core.skills.signing import source_snapshot

OWNER = Principal(channel="web", admin=True)
GUEST = Principal(channel="telegram", sender="guest", admin=False)
REAL_DISCOVER = SkillLoader.discover


@pytest.fixture
def cast(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    monkeypatch.setattr(loader_mod, "SKILLS_DIR", tmp_path / "skills")
    monkeypatch.setattr(loader_mod, "_user_skills_dir", lambda: None)
    monkeypatch.setattr(loader_mod, "_LIVE_LOADER", None)
    monkeypatch.setattr(loader_mod.safe_mode, "enabled", lambda: False)
    monkeypatch.delenv("JARVIS_REQUIRE_SIGNED_SKILLS", raising=False)
    monkeypatch.delenv("JARVIS_SKILL_SIGNING_KEY", raising=False)
    loader_mod.SKILLS_DIR.mkdir()
    for kind in load_set.KINDS:
        load_set.begin(kind)
    approvals = SkillApprovalStore(tmp_path / "approvals.json")
    _write_skill(loader_mod.SKILLS_DIR, "alpha", "Alpha")
    live = SkillLoader(approval_store=approvals)
    live.discover()
    orch = SimpleNamespace(skills=live, commands=build_default_registry(),
                           curator=SimpleNamespace(_loader=live),
                           curator_operations=SimpleNamespace(loader=live))
    yield SimpleNamespace(tmp_path=tmp_path, root=loader_mod.SKILLS_DIR,
                          approvals=approvals, live=live, orch=orch)
    for kind in load_set.KINDS:
        load_set.begin(kind)


def _write_skill(root: Path, folder: str, name: str, *, detail: str = "", code: bool = False) -> Path:
    target = root / folder
    target.mkdir(exist_ok=True)
    (target / "SKILL.md").write_text(f"# {name}\n\n> {detail or 'A helper.'}\n", encoding="utf-8")
    if code:
        (target / "main.py").write_text("def register(skill):\n    pass\n", encoding="utf-8")
    return target


async def _command(cast, text: str, principal: Principal = OWNER):
    return await cast.orch.commands.dispatch(text, orch=cast.orch, principal=principal)


def _hold_stage(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def slow(self, *args, **kwargs):
        result = REAL_DISCOVER(self, *args, **kwargs)
        if kwargs.get("staging"):
            entered.set()
            assert release.wait(5), "staged scan was not released"
        return result

    monkeypatch.setattr(SkillLoader, "discover", slow)
    return entered, release


async def _await_entered(event):
    assert await asyncio.to_thread(event.wait, 4), "staged scan did not start"


async def test_owner_registry_alias_and_added_removed_changed_report(cast):
    registry = cast.orch.commands
    command = registry.get("reload_skills")
    assert command is not None and registry.get("reload-skills") is command
    assert CommandRegistry.parse("/reload-skills") == ("reload-skills", "")
    denied = await _command(cast, "/reload-skills", GUEST)
    assert denied.status == "refused" and cast.live.get_skill("Alpha") is not None
    refused = await _command(cast, "/reload_skills now")
    assert refused.status == "answered" and "nothing changed" in refused.reply.lower()

    _write_skill(cast.root, "alpha", "Alpha", detail="Updated helper.")
    _write_skill(cast.root, "beta", "Beta")
    result = await _command(cast, "/reload-skills")
    assert result.status == "answered"
    assert "Alpha" in result.reply and "changed" in result.reply.lower()
    assert "Beta" in result.reply and "added" in result.reply.lower()
    assert cast.live.get_skill("Beta") is not None
    assert cast.orch.curator._loader is cast.live
    assert cast.orch.curator_operations.loader is cast.live

    (cast.root / "beta" / "SKILL.md").unlink()
    (cast.root / "beta").rmdir()
    result = await _command(cast, "/reload_skills")
    assert "Beta" in result.reply and "removed" in result.reply.lower()
    assert cast.live.get_skill("Beta") is None


def test_staged_discovery_does_not_publish_loader_or_load_set(cast, monkeypatch):
    before_loader = loader_mod._LIVE_LOADER
    before_load_set = load_set.status("skills")
    called = []
    monkeypatch.setattr(cast.approvals, "prune_missing", lambda: called.append("pruned"))
    candidate = SkillLoader(approval_store=cast.approvals)
    _write_skill(cast.root, "beta", "Beta")
    result = candidate.discover(staging=True, declared_lists={"disabled": [], "only": []})
    assert "Beta" in result
    assert loader_mod._LIVE_LOADER is before_loader and before_loader() is cast.live
    assert load_set.status("skills") == before_load_set
    assert called == []


async def test_malformed_candidate_refuses_without_partial_registry_change(cast):
    old_map = cast.live.skills
    broken = cast.root / "broken"
    broken.mkdir()
    (broken / "SKILL.md").write_bytes(b"\xff\xfe")
    result = await _command(cast, "/reload_skills")
    assert "broken" in result.reply.lower() and "unchanged" in result.reply.lower()
    assert cast.live.skills is old_map and cast.live.get_skill("Alpha") is old_map["Alpha"]


async def test_load_set_and_pending_review_remain_inert_after_reload(cast):
    _write_skill(cast.root, "beta", "Beta")
    pending = _write_skill(cast.root, "gamma", "Gamma", code=True)
    (pending / "PENDING_REVIEW").write_text("", encoding="utf-8")
    settings_db.put_category("loadset", {"skills_disabled": "Beta"})
    result = await _command(cast, "/reload_skills")
    assert "Beta" in result.reply and "Skipped" in result.reply
    assert "Gamma" in result.reply and "Pending review" in result.reply
    assert cast.live.get_skill("Beta") is None
    assert load_set.status("skills")["skipped"] == ["Beta"]
    gamma = cast.live.get_skill("Gamma")
    assert gamma.sandboxed and gamma.module is None and not gamma.owner_vouched
    again = await _command(cast, "/reload_skills")
    assert "Gamma" in again.reply and "Unverified" in again.reply


async def test_existing_approval_is_reused_for_a_code_skill(cast):
    target = _write_skill(cast.root, "beta", "Beta", code=True)
    cast.approvals.approve(target, snapshot=source_snapshot(target))
    result = await _command(cast, "/reload_skills")
    assert "Beta" in result.reply and "Added" in result.reply
    loaded = cast.live.get_skill("Beta")
    assert loaded.owner_vouched and not loaded.sandboxed and loaded.module is not None


async def test_concurrent_install_and_load_set_change_refuse_stale_stage(cast, monkeypatch):
    _write_skill(cast.root, "beta", "Beta")
    entered, release = _hold_stage(monkeypatch)
    old_map = cast.live.skills
    task = asyncio.create_task(_command(cast, "/reload_skills"))
    try:
        await _await_entered(entered)
        assert cast.live.skills is old_map and cast.live.get_skill("Beta") is None
        live_added = object()
        cast.live.skills["concurrent"] = live_added
    finally:
        release.set()
    result = await task
    assert "changed during reload" in result.reply.lower()
    assert cast.live.skills is old_map and cast.live.skills["concurrent"] is live_added

    # Replacing the mapping with equal slots is still a newer live mutation.
    entered, release = _hold_stage(monkeypatch)
    task = asyncio.create_task(_command(cast, "/reload_skills"))
    try:
        await _await_entered(entered)
        newer_map = dict(cast.live.skills)
        cast.live.skills = newer_map
    finally:
        release.set()
    result = await task
    assert "changed during reload" in result.reply.lower()
    assert cast.live.skills is newer_map and cast.live.get_skill("Beta") is None

    entered, release = _hold_stage(monkeypatch)
    task = asyncio.create_task(_command(cast, "/reload_skills"))
    try:
        await _await_entered(entered)
        settings_db.put_category("loadset", {"skills_disabled": "beta"})
    finally:
        release.set()
    result = await task
    assert "policy changed" in result.reply.lower()
    assert cast.live.get_skill("Beta") is None


async def test_approval_revoked_during_stage_cannot_publish_code(cast, monkeypatch):
    target = _write_skill(cast.root, "beta", "Beta", code=True)
    cast.approvals.approve(target, snapshot=source_snapshot(target))
    entered, release = _hold_stage(monkeypatch)
    task = asyncio.create_task(_command(cast, "/reload_skills"))
    try:
        await _await_entered(entered)
        assert cast.live.get_skill("Beta") is None
        assert cast.approvals.revoke(target)
    finally:
        release.set()
    result = await task
    assert "policy changed" in result.reply.lower()
    assert cast.live.get_skill("Beta") is None
    assert loader_mod._LIVE_LOADER is not None and loader_mod._LIVE_LOADER() is cast.live


async def test_cancelled_scan_keeps_single_flight_until_worker_exits(cast, monkeypatch):
    _write_skill(cast.root, "beta", "Beta")
    entered, release = _hold_stage(monkeypatch)
    old_map = cast.live.skills
    first = asyncio.create_task(_command(cast, "/reload_skills"))
    try:
        await _await_entered(entered)
        first.cancel()
        await asyncio.sleep(0)
        second = await _command(cast, "/reload_skills")
        assert "already running" in second.reply.lower()
        assert cast.live.skills is old_map
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert cast.live.skills is old_map and cast.live.get_skill("Beta") is None
    retry = await _command(cast, "/reload_skills")
    assert "Beta" in retry.reply and cast.live.get_skill("Beta") is not None


async def test_policy_change_during_candidate_validation_blocks_swap(cast, monkeypatch):
    _write_skill(cast.root, "beta", "Beta")
    entered, release = threading.Event(), threading.Event()
    real_admitted = maintenance_commands._candidate_still_admitted

    def held_validation(candidate, policy):
        result = real_admitted(candidate, policy)
        entered.set()
        assert release.wait(5), "validation was not released"
        return result

    monkeypatch.setattr(maintenance_commands, "_candidate_still_admitted", held_validation)
    old_map = cast.live.skills
    task = asyncio.create_task(_command(cast, "/reload_skills"))
    try:
        await _await_entered(entered)
        settings_db.put_category("loadset", {"skills_disabled": "Beta"})
    finally:
        release.set()
    result = await task
    assert "policy changed" in result.reply.lower()
    assert cast.live.skills is old_map and cast.live.get_skill("Beta") is None
