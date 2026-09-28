"""Actual named command registry/engines, approved state and bounded processes."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agents.core import settings_db
from agents.core.voice import command_settings
from agents.core.voice import local_providers as lp
from agents.core.voice import stt as sm
from agents.core.voice import tts as tm
from tests.test_h517_voice_kernel import make_rig
from tests.test_h517_voice_revision import HeldSlot
from tests.test_h613_piper_command_voice import WAV, _fake, _py, _records
from tests.test_h613_piper_command_voice import env as env


@pytest.mark.parametrize("selector", ["provider:missing", "provider:UPPER", "provider:edge"])
@pytest.mark.asyncio
async def test_explicit_missing_named_tts_never_reaches_vendor_fallback(env, monkeypatch, selector):
    monkeypatch.setattr(tm, "HAS_EDGE", True)
    engine = tm.TTSEngine(consent_getter=lambda: True)
    engine._speak_edge = AsyncMock(return_value="vendor-fallback")
    engine._speak_command = AsyncMock(return_value="legacy-command")
    assert await engine.speak("hello world", voice=selector, lang="en") is None
    engine._speak_edge.assert_not_awaited()
    engine._speak_command.assert_not_awaited()


@pytest.fixture
def named(env, monkeypatch):
    rig = make_rig(env.tmp, monkeypatch)
    env.rig = rig
    yield env
    rig.q.close()


async def approve(named, side, provider_id, *, transcript=None, failing=False):
    script = _fake(named.tmp / "opt" / f"{side}-{provider_id}.py", named.tmp)
    source = script.read_text().replace(repr(WAV), repr(WAV + provider_id.encode()))
    source = source.replace('print("salut lume")', f'print({(transcript or provider_id + " speech")!r})')
    if failing:
        source += "\nraise SystemExit(3)\n"
    script.write_text(source)
    argv = [_py(), str(script)] + (["--out", "{output}"] if side == "tts" else ["--audio", "{audio}"])
    code, result = await command_settings.request(named.rig.orch, side, argv, provider_id=provider_id)
    assert code == 202, result
    task_id = result["pending"]
    await named.rig.worker.apply_decision(task_id, "accept", decided_by="owner")
    await named.rig.worker.tick()
    assert named.rig.q.get(task_id).status == "done", named.rig.q.get(task_id).result
    assert lp.command_ready(side, provider_id=provider_id).ok
    return argv


def stt_engine(model=None):
    engine = sm.STTEngine.__new__(sm.STTEngine)
    engine._model = model
    engine.beam_size = 1
    return engine


@pytest.mark.parametrize("side", ["tts", "stt"])
@pytest.mark.asyncio
async def test_two_registered_programs_use_actual_registry_lookup_and_distinct_processes(named, monkeypatch, side):
    from agents.core.media_providers import ProviderRegistry
    await approve(named, side, "alpha")
    await approve(named, side, "beta")
    calls = []
    original = ProviderRegistry.get

    def get(self, kind, provider_id):
        calls.append((kind, provider_id))
        return original(self, kind, provider_id)

    monkeypatch.setattr(ProviderRegistry, "get", get)
    for provider_id in ("alpha", "beta"):
        if side == "tts":
            engine = tm.TTSEngine(default_voice="provider:" + provider_id)
            result = await engine.speak("hello world", lang="ro")
            assert Path(result).read_bytes() == WAV + provider_id.encode()
        else:
            settings_db.put_category("voice", {"stt_engine": "command", "stt_command_provider": provider_id})
            result = await stt_engine().transcribe_async(WAV, "en")
            assert result == provider_id + " speech"
    assert calls == [(side, "alpha"), (side, "beta")]
    assert len(_records(named.tmp)) == 2


@pytest.mark.asyncio
async def test_named_runtime_failure_uses_safe_fallback_without_legacy_command(named, monkeypatch):
    await approve(named, "tts", "broken", failing=True)
    monkeypatch.setattr(tm, "HAS_EDGE", True)
    engine = tm.TTSEngine()
    engine._speak_edge = AsyncMock(return_value="safe-edge")
    engine._speak_command = AsyncMock(return_value="legacy")
    assert await engine.speak("hello", voice="provider:broken", lang="en") == "safe-edge"
    engine._speak_command.assert_not_awaited()
    assert engine._speak_edge.await_args.args[1] == "en-GB-RyanNeural"


@pytest.mark.parametrize("consent,local_only", [(False, False), (True, True)])
@pytest.mark.asyncio
async def test_named_persona_and_local_only_gates_precede_execution(named, monkeypatch, consent, local_only):
    await approve(named, "tts", "fish_test")
    settings_db.put_category("voice", {"local_only": local_only})
    monkeypatch.setattr(tm, "HAS_EDGE", True)
    engine = tm.TTSEngine(consent_getter=lambda: consent)
    engine._speak_edge = AsyncMock(return_value="safe-edge")
    engine._speak_fish = AsyncMock(return_value="vendor")
    engine._speak_piper = AsyncMock(return_value="safe-local")
    result = await engine.speak("hello", voice="provider:fish_test", lang="en")
    assert result == ("safe-local" if local_only else "safe-edge")
    assert _records(named.tmp) == []
    engine._speak_fish.assert_not_awaited()


@pytest.mark.asyncio
async def test_consented_vendor_substring_in_named_pin_runs_command_not_vendor(named):
    await approve(named, "tts", "fish_test")
    engine = tm.TTSEngine(consent_getter=lambda: True)
    engine._speak_fish = AsyncMock(return_value="vendor")
    path = await engine.speak("hello", voice="provider:fish_test", lang="en")
    assert Path(path).read_bytes() == WAV + b"fish_test"
    engine._speak_fish.assert_not_awaited()


@pytest.mark.parametrize("mode,loaded,expected", [("auto", True, "from whisper"),
                                                ("whisper", False, "[STT unavailable]"),
                                                ("command", True, "alpha speech")])
@pytest.mark.asyncio
async def test_named_stt_preserves_native_mode_preference(named, mode, loaded, expected):
    await approve(named, "stt", "alpha")
    class Model:
        def transcribe(self, *args, **kwargs):
            return [SimpleNamespace(text="from whisper")], SimpleNamespace(duration=3)
    settings_db.put_category("voice", {"stt_engine": mode, "stt_command_provider": "alpha"})
    assert await stt_engine(Model() if loaded else None).transcribe_async(WAV, "en") == expected
    assert len(_records(named.tmp)) == (1 if mode == "command" else 0)


@pytest.mark.asyncio
async def test_missing_selected_stt_does_not_use_legacy_or_whisper(named, monkeypatch):
    settings_db.put_category("voice", {"stt_engine": "command", "stt_command_provider": "missing"})
    engine = stt_engine(object())
    engine._transcribe_command = AsyncMock(return_value="legacy")
    assert await engine.transcribe_async(WAV, "en") == "[STT unavailable]"
    engine._transcribe_command.assert_not_awaited()
    assert not lp.stt_available(True)


@pytest.mark.parametrize("side", ["tts", "stt"])
@pytest.mark.parametrize("change", ["selector", "revoked", "reapproved"])
@pytest.mark.asyncio
async def test_named_waiter_pins_id_and_original_row_revision(named, monkeypatch, side, change):
    from agents.core.voice import provider_store
    await approve(named, side, "alpha")
    await approve(named, side, "beta")
    settings_db.put_category("voice", {"stt_engine": "command", "stt_command_provider": "alpha"})
    engine = tm.TTSEngine(default_voice="provider:alpha") if side == "tts" else stt_engine()
    gate = HeldSlot()
    monkeypatch.setattr(lp, "_slot", lambda: gate)
    async def invoke():
        return await engine.speak("hello", lang="en") if side == "tts" else await engine.transcribe_async(WAV, "en")
    pending = asyncio.create_task(invoke())
    try:
        await asyncio.wait_for(gate.waiting.wait(), 2)
        if change == "selector":
            if side == "tts":
                engine.default_voice = "provider:beta"
            else:
                settings_db.put_category("voice", {"stt_command_provider": "beta"})
        elif change == "revoked":
            provider_store.clear(side, "alpha")
        else:
            value = provider_store.load(side, "alpha")
            provider_store.save_approved(side, "alpha", value, expected_revision=value["provider_revision"])
    finally:
        gate.release()
        result = await pending
    if change == "selector":
        assert Path(result).read_bytes() == WAV + b"alpha" if side == "tts" else result == "alpha speech"
        assert len(_records(named.tmp)) == 1
    else:
        assert result is None if side == "tts" else result == "[STT error: command changed_before_spawn]"
        assert _records(named.tmp) == []


@pytest.mark.asyncio
async def test_named_metadata_does_not_spawn_or_load_engines(named, monkeypatch):
    from agents.core.voice.provider_registry import speech_registry
    await approve(named, "tts", "alpha")
    async def forbidden(*args, **kwargs):
        raise AssertionError("metadata spawned a process")
    monkeypatch.setattr(lp, "_spawn", forbidden)
    registry = speech_registry()
    provider = registry.get("tts", "alpha")
    assert provider.name == "alpha" and provider.kind == "tts" and provider.is_available()
    assert provider.get_setup_schema()["badge"] == "approved-command"
    assert lp.named_command_status("tts")[0]["selector"] == "provider:alpha"
    assert _records(named.tmp) == []


@pytest.mark.asyncio
async def test_stt_name_pinned_before_first_async_choice(named, monkeypatch):
    await approve(named, "stt", "alpha")
    await approve(named, "stt", "beta")
    settings_db.put_category("voice", {"stt_engine": "command", "stt_command_provider": "alpha"})
    engine = stt_engine()
    entered, release = asyncio.Event(), asyncio.Event()
    original = asyncio.to_thread
    async def delayed(func, *args, **kwargs):
        if getattr(func, "__self__", None) is engine and getattr(func, "__name__", "") == "_choice":
            entered.set()
            await release.wait()
        return await original(func, *args, **kwargs)
    monkeypatch.setattr(asyncio, "to_thread", delayed)
    pending = asyncio.create_task(engine.transcribe_async(WAV, "en"))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        settings_db.put_category("voice", {"stt_command_provider": "beta"})
    finally:
        release.set()
        result = await pending
    assert result == "alpha speech" and len(_records(named.tmp)) == 1


@pytest.mark.asyncio
async def test_legacy_private_command_overrides_keep_old_signatures(env, monkeypatch):
    monkeypatch.setattr(tm, "HAS_EDGE", True)
    engine = tm.TTSEngine(consent_getter=lambda: True)
    engine._speak_command = AsyncMock(return_value="legacy-result")
    engine._speak_fish = AsyncMock(return_value="vendor")
    assert await engine.speak("hello", voice="command:fish_anything", lang="en") == "legacy-result"
    engine._speak_command.assert_awaited_once_with("hello", "en")
    engine._speak_fish.assert_not_awaited()
    transcriber = stt_engine()
    transcriber._choice = lambda: "command"
    transcriber._transcribe_command = AsyncMock(return_value="legacy speech")
    assert await transcriber.transcribe_async(WAV, "en") == "legacy speech"
    transcriber._transcribe_command.assert_awaited_once_with(WAV, "en")


@pytest.mark.parametrize("side", ["tts", "stt"])
@pytest.mark.parametrize("guard", ["unarmed", "safe_mode"])
@pytest.mark.asyncio
async def test_named_commands_still_respect_arming_and_safe_mode(named, monkeypatch, side, guard):
    await approve(named, side, "alpha")
    if guard == "unarmed":
        monkeypatch.setenv(lp.ARM_ENV, "0")
    else:
        monkeypatch.setenv("JARVIS_SAFE_MODE", "1")
    assert not lp.command_ready(side, provider_id="alpha").ok
    if side == "tts":
        assert await lp.speak_command("hello", "en", temp_dir=named.temp, provider_id="alpha") is None
    else:
        assert await lp.transcribe_command(WAV, "en", temp_dir=named.temp, provider_id="alpha") == "[STT unavailable]"
    assert _records(named.tmp) == []


@pytest.mark.parametrize("transcript", ["Thanks for watching!", ""])
@pytest.mark.asyncio
async def test_named_stt_hallucination_and_silence_sentinels_remain_exact(named, transcript):
    await approve(named, "stt", "alpha", transcript=transcript or " ")
    settings_db.put_category("voice", {"stt_engine": "command", "stt_command_provider": "alpha"})
    assert await stt_engine().transcribe_async(WAV, "en") == "[silence]"


@pytest.mark.asyncio
async def test_unreadable_named_store_refuses_explicit_pin_without_legacy_fallback(named, monkeypatch):
    from agents.core.voice import provider_store
    await approve(named, "tts", "alpha")
    def broken(*args, **kwargs):
        raise provider_store.ProviderStoreError("unreadable")
    monkeypatch.setattr(provider_store, "list_records", broken)
    monkeypatch.setattr(tm, "HAS_EDGE", True)
    engine = tm.TTSEngine()
    engine._speak_edge = AsyncMock(return_value="vendor")
    assert await engine.speak("hello", voice="provider:alpha") is None
    engine._speak_edge.assert_not_awaited()
    assert _records(named.tmp) == []


@pytest.mark.asyncio
async def test_stt_whisper_handoff_cannot_retarget_named_provider(named, monkeypatch):
    await approve(named, "stt", "alpha")
    await approve(named, "stt", "beta")
    settings_db.put_category("voice", {"stt_engine": "auto", "stt_command_provider": "alpha"})
    engine = stt_engine(model=object())
    original = engine.transcribe

    def delayed(audio, language):
        # The existing thread handoff reevaluates the engine choice. A change
        # may select a command, but must not borrow a different named identity.
        settings_db.put_category("voice", {"stt_engine": "command", "stt_command_provider": "beta"})
        return original(audio, language)

    monkeypatch.setattr(engine, "transcribe", delayed)
    assert await engine.transcribe_async(WAV, "en") == "alpha speech"
    assert len(_records(named.tmp)) == 1
