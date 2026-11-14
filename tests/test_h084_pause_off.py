"""H084 donor /pause off owner recovery, without touching the host e-stop."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.core import estop
from agents.core.commands import ADMIN, Principal, build_default_registry

OWNER = Principal(channel="telegram", sender="42", admin=True)
GUEST = Principal(channel="telegram", sender="7", admin=False)


@pytest.fixture
def fake_estop(monkeypatch):
    state = {"engaged": True, "engages": [], "disengages": 0}

    def engage(reason):
        state["engaged"] = True
        state["engages"].append(reason)

    def disengage():
        state["disengages"] += 1
        was_engaged, state["engaged"] = state["engaged"], False
        return was_engaged

    monkeypatch.setattr(estop, "engage", engage)
    monkeypatch.setattr(estop, "disengage", disengage)
    return state


async def _send(text, *, principal=OWNER):
    return await build_default_registry().dispatch(text, orch=SimpleNamespace(), principal=principal)


@pytest.mark.asyncio
@pytest.mark.parametrize("word", ["off", "resume", "stop", "disengage", "OFF"])
async def test_exact_pause_release_words_use_existing_owner_recovery(fake_estop, word):
    result = await _send(f"/pause {word}")
    assert result.status == "answered" and "lifted" in result.reply
    assert fake_estop == {"engaged": False, "engages": [], "disengages": 1}


@pytest.mark.asyncio
async def test_pause_off_when_not_engaged_is_truthful(fake_estop):
    fake_estop["engaged"] = False
    result = await _send("/pause   off  ")
    assert "was not engaged" in result.reply
    assert fake_estop["disengages"] == 1 and fake_estop["engages"] == []


@pytest.mark.asyncio
async def test_guest_cannot_release_and_stop_spelling_still_engages(fake_estop):
    registry = build_default_registry()
    assert registry.get("pause").tier == registry.get("stop").tier == ADMIN
    denied = await _send("/pause off", principal=GUEST)
    assert denied.status == "refused" and "owner" in denied.reply.lower()
    assert fake_estop["disengages"] == 0 and fake_estop["engages"] == []
    stopped = await _send("/stop off")
    assert stopped.status == "answered" and "engaged" in stopped.reply.lower()
    assert fake_estop["engages"] == ["off"] and fake_estop["disengages"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["offline", "off now", "resume work", "disengaged", "stop this job"])
async def test_only_exact_pause_word_releases_unknown_reason_text_engages(fake_estop, reason):
    result = await _send(f"/pause {reason}")
    assert result.status == "answered" and "engaged" in result.reply.lower()
    assert fake_estop["engages"] == [reason] and fake_estop["disengages"] == 0


@pytest.mark.asyncio
async def test_bare_pause_preserves_existing_reason_and_engagement_time(fake_estop, monkeypatch):
    original = {"reason": "private credential value", "engaged_at": "2026-01-02T03:04:05Z"}
    monkeypatch.setattr(estop, "get_state", lambda: dict(original))
    result = await _send("/pause")
    assert result.status == "answered" and "already" in result.reply.lower()
    assert "/pause off" in result.reply
    assert "private credential value" not in result.reply
    assert fake_estop["engages"] == [] and fake_estop["disengages"] == 0
    assert original == {"reason": "private credential value", "engaged_at": "2026-01-02T03:04:05Z"}


@pytest.mark.asyncio
async def test_explicit_pause_reason_updates_existing_pause(fake_estop, monkeypatch):
    monkeypatch.setattr(estop, "get_state", lambda: {"reason": "old", "engaged_at": "old-time"})
    result = await _send("/pause new reason")
    assert "engaged" in result.reply.lower()
    assert fake_estop["engages"] == ["new reason"] and fake_estop["disengages"] == 0


@pytest.mark.asyncio
async def test_pause_help_advertises_off_and_stop_description_is_explicit(fake_estop):
    registry = build_default_registry()
    assert registry.get("pause").usage == "[reason|off]"
    assert "engage the emergency stop" in registry.get("stop").description
    assert "same as /pause" not in registry.get("stop").description
    owner_help = await registry.dispatch("/help", orch=SimpleNamespace(commands=registry), principal=OWNER)
    assert "/pause [reason|off]" in owner_help.reply
