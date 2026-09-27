"""Original approval identity remains bound across the real command slot wait."""

import asyncio
from pathlib import Path

import pytest

from agents.core import settings_db
from agents.core.voice import command_settings
from agents.core.voice import local_providers as lp
from tests.test_h613_piper_command_voice import WAV, _approve, _fake, _py, _records
from tests.test_h613_piper_command_voice import env as env


class HeldSlot(asyncio.Semaphore):
    def __init__(self):
        super().__init__(0)
        self.waiting = asyncio.Event()

    async def acquire(self):
        self.waiting.set()
        return await super().acquire()


async def invoke(env, side):
    if side == "tts":
        return await lp.speak_command("hello world", "en", temp_dir=env.temp)
    return await lp.transcribe_command(WAV, "en", temp_dir=env.temp)


def provider(env, side, *, script=False):
    file = _fake(env.tmp / "opt" / ("provider.py" if script else "provider"), env.tmp)
    argv = [_py(), str(file)] if script else [str(file)]
    argv += ["--out", "{output}"] if side == "tts" else ["--audio", "{audio}"]
    return file, argv


@pytest.mark.parametrize("side", ["tts", "stt"])
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.asyncio
async def test_unchanged_original_approval_runs_after_slot_release(env, monkeypatch, side, legacy):
    monkeypatch.setenv(lp.ARM_ENV, "1")
    _, argv = provider(env, side)
    assert (await _approve(env, side, argv))["status"] == "ok"
    if legacy:
        value = lp.stored_command(side)
        value.pop("approved_task", None)
        value.pop("approved_at", None)
        settings_db.put_category("voice", {f"{side}_command": value})
    gate = HeldSlot()
    monkeypatch.setattr(lp, "_slot", lambda: gate)
    pending = asyncio.create_task(invoke(env, side))
    try:
        await asyncio.wait_for(gate.waiting.wait(), 2)
        assert _records(env.tmp) == [] and not pending.done()
    finally:
        gate.release()
        result = await pending
    if side == "tts":
        assert Path(result).read_bytes() == WAV
    else:
        assert result == "salut lume"
    assert len(_records(env.tmp)) == 1


@pytest.mark.parametrize("side", ["tts", "stt"])
@pytest.mark.parametrize("change", ["reapproved", "executable", "script", "legacy_executable",
                                    "legacy_script", "revoked", "unarmed", "safe_mode"])
@pytest.mark.asyncio
async def test_waiting_invocation_cannot_borrow_new_approval_even_with_identical_argv(
    env, monkeypatch, side, change,
):
    monkeypatch.setenv(lp.ARM_ENV, "1")
    file, argv = provider(env, side, script=change.endswith("script"))
    assert (await _approve(env, side, argv))["status"] == "ok"
    legacy = change.startswith("legacy_")
    if legacy:
        value = lp.stored_command(side)
        value.pop("approved_task", None)
        value.pop("approved_at", None)
        settings_db.put_category("voice", {f"{side}_command": value})
    original = lp.stored_command(side)
    gate = HeldSlot()
    monkeypatch.setattr(lp, "_slot", lambda: gate)
    pending = asyncio.create_task(invoke(env, side))
    try:
        await asyncio.wait_for(gate.waiting.wait(), 2)
        assert _records(env.tmp) == [] and not pending.done()
        if change in {"reapproved", "executable", "script"} or legacy:
            if change != "reapproved":
                file.write_text(file.read_text() + "\n# new approved implementation\n")
            assert (await _approve(env, side, argv))["status"] == "ok"
            replacement = lp.stored_command(side)
            if legacy:
                replacement.pop("approved_task", None)
                replacement.pop("approved_at", None)
                settings_db.put_category("voice", {f"{side}_command": replacement})
            assert replacement["argv"] == original["argv"]
            if not legacy:
                assert replacement["approved_task"] != original["approved_task"]
            if change != "reapproved":
                assert replacement["bound"] != original["bound"]
            assert lp.command_ready(side).ok
        elif change == "revoked":
            assert (await command_settings.clear(None, side))[0] == 200
        elif change == "unarmed":
            monkeypatch.setenv(lp.ARM_ENV, "0")
        else:
            monkeypatch.setenv("JARVIS_SAFE_MODE", "1")
    finally:
        gate.release()
        result = await pending
    assert result is None if side == "tts" else result == "[STT error: command changed_before_spawn]"
    assert _records(env.tmp) == []
    assert list(env.temp.glob("response_command_*")) == []
