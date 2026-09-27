"""Join signed speech registration to original-approval command execution."""

import asyncio
from pathlib import Path

import pytest

from agents.core.voice import command_settings
from agents.core.voice import local_providers as lp
from tests.test_h517_voice_kernel import make_rig
from tests.test_h517_voice_revision import HeldSlot
from tests.test_h613_piper_command_voice import WAV, _fake, _py, _records


@pytest.mark.parametrize("side", ["tts", "stt"])
@pytest.mark.asyncio
async def test_signed_replacement_refuses_old_waiter_and_fresh_invocation_runs(
    tmp_path, monkeypatch, side,
):
    rig = make_rig(tmp_path, monkeypatch)
    program = _fake(tmp_path / "speech.py", tmp_path)
    argv = [_py(), str(program)] + (
        ["--out", "{output}"] if side == "tts" else ["--audio", "{audio}"]
    )
    temp = tmp_path / "runs"

    async def install():
        code, response = await command_settings.request(rig.orch, side, argv)
        assert code == 202, response
        task_id = response["pending"]
        queued = rig.q.get(task_id)
        assert queued.status == "blocked" and queued.risk_tier == 3
        assert queued.mediation_receipt["kind"] == command_settings.APPROVAL_KIND
        assert lp.stored_command(side).get("approved_task") != task_id
        await rig.worker.apply_decision(task_id, "accept", decided_by="owner")
        await rig.worker.tick()
        assert rig.q.get(task_id).status == "done", rig.q.get(task_id).result
        value = lp.stored_command(side)
        assert value["approved_task"] == task_id and value["argv"] == argv
        return value

    async def invoke():
        if side == "tts":
            return await lp.speak_command("hello world", "en", temp_dir=temp)
        return await lp.transcribe_command(WAV, "en", temp_dir=temp)

    try:
        original = await install()
        gate = HeldSlot()
        monkeypatch.setattr(lp, "_slot", lambda: gate)
        pending = asyncio.create_task(invoke())
        try:
            await asyncio.wait_for(gate.waiting.wait(), 2)
            assert not pending.done() and _records(tmp_path) == []
            replacement = await install()
            assert replacement["argv"] == original["argv"]
            assert replacement["bound"] == original["bound"]
            assert replacement["approved_task"] != original["approved_task"]
        finally:
            gate.release()
            refused = await pending
        assert refused is None if side == "tts" else refused == "[STT error: command changed_before_spawn]"
        assert _records(tmp_path) == []
        gate.release()
        fresh = await invoke()
        if side == "tts":
            assert Path(fresh).read_bytes() == WAV
        else:
            assert fresh == "salut lume"
        assert len(_records(tmp_path)) == 1
        stats = rig.q.verified_mediation_stats()
        assert stats["valid"] and stats["authorized_enqueue"] == 2
    finally:
        rig.q.close()
