"""H613 — Piper TTS and the owner's governed command providers for TTS / STT.

Piper: ``piper:<model>`` voices (and bare ``piper``) run the piper package when it
imports, else the ``piper`` binary as an argv list with the text on stdin and the output
under the TTS temp dir; any failure falls back to the safe default voice, and with
``voice.local_only`` Piper is tried before any cloud voice (edge is never called).

Command providers: ``voice.tts_command`` / ``voice.stt_command`` hold an argv template
with whole-element placeholders. A setting that makes the hub run a program is a
host-exec capability: the rows are ROUTE_ONLY, their only writer is
``POST /api/admin/voice/commands`` which sends a set to the irreversible approval tier,
a run also needs ``JARVIS_VOICE_COMMANDS=1`` and is off in safe mode, and every spawn is
re-validated against the program identity recorded at approval. No shell, ever.

Fakes are Python scripts in ``tmp_path`` with a ``#!<sys.executable>`` shebang that
record their argv, stdin and cwd.
"""
from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core import settings_db
from agents.core.autonomy import irreversible
from agents.core.voice import command_settings
from agents.core.voice import local_providers as lp
from agents.core.voice import stt as stt_module
from agents.core.voice import tts as tts_module
from agents.core.voice.tts import TTSEngine

WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x10\x00\x00\x00\x01\x00\x01\x00" + b"\x00" * 20
ADMIN = {"X-Admin-Token": "adm-h613"}

FAKE = r'''#!{python}
import json, os, sys, time
REC = {rec!r}
MODE = {mode!r}
mode = open(MODE).read().strip() if os.path.exists(MODE) else "ok"
argv = sys.argv
data = b"" if {no_stdin} else sys.stdin.buffer.read()
def opt(name):
    return argv[argv.index(name) + 1] if name in argv else None
entry = {{"argv": argv, "stdin": data.decode("utf-8", "replace"), "cwd": os.getcwd(), "pid": os.getpid()}}
tf = opt("--in")
if tf:
    entry["text_file"] = open(tf, encoding="utf-8").read()
    entry["text_file_mode"] = oct(os.stat(tf).st_mode & 0o777)
audio = opt("--audio")
if audio:
    entry["audio"] = open(audio, "rb").read().hex()
    entry["audio_mode"] = oct(os.stat(audio).st_mode & 0o777)
    entry["run_dir_mode"] = oct(os.stat(os.path.dirname(audio)).st_mode & 0o777)
with open(REC, "a") as fh:
    fh.write(json.dumps(entry) + "\n")
out = opt("--output_file") or opt("--out")
if mode == "sleep":
    time.sleep(30)
if mode == "fail":
    sys.exit(3)
if mode == "flood":
    chunk = b"x" * 65536
    for _ in range(320):
        sys.stdout.buffer.write(chunk)
    sys.stdout.flush()
if out:
    if mode == "nonwav":
        open(out, "wb").write(b"hello, not audio")
    elif mode == "big":
        open(out, "wb").write({wav!r} + b"\0" * (9 * 1024 * 1024))
    elif mode == "symlink":
        outside = os.path.join({outside!r}, "stolen.wav")
        open(outside, "wb").write({wav!r})
        os.symlink(outside, out)
    elif mode == "empty":
        pass
    else:
        open(out, "wb").write({wav!r})
if audio:
    if mode == "silent":
        pass
    elif mode == "hallucinate":
        print("Thanks for watching!")
    else:
        print("salut lume")
'''


def _fake(path: Path, tmp: Path, *, no_stdin: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(FAKE.format(python=sys.executable, rec=str(tmp / "rec.jsonl"), mode=str(tmp / "mode.txt"),
                                no_stdin=no_stdin, wav=WAV, outside=str(tmp / "outside")), encoding="utf-8")
    path.chmod(0o755)
    return path


def _records(tmp: Path) -> list[dict]:
    rec = tmp / "rec.jsonl"
    if not rec.exists():
        return []
    return [json.loads(line) for line in rec.read_text(encoding="utf-8").splitlines() if line.strip()]


def _mode(tmp: Path, mode: str) -> None:
    (tmp / "mode.txt").write_text(mode, encoding="utf-8")


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / "outside").mkdir()
    monkeypatch.setenv("JARVIS_HOME", str(home))
    for name in ("JARVIS_VOICE_COMMANDS", "JARVIS_SAFE_MODE", "JARVIS_VOICE_COMMAND_TIMEOUT_S",
                 "JARVIS_TASK_MEDIATION", "XTTS_SERVER_URL", "ELEVENLABS_API_KEY", "FISH_AUDIO_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False, raising=False)
    settings_db.init_db(force=True)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    monkeypatch.setenv("PATH", str(bindir))
    temp = tmp_path / "tts"
    monkeypatch.setattr(tts_module, "TEMP_DIR", temp)
    monkeypatch.setattr(stt_module, "TEMP_DIR", temp, raising=False)
    monkeypatch.setattr(lp, "_import_piper", lambda: None)
    monkeypatch.setattr(lp, "_logged", set())
    models = tmp_path / "models"
    models.mkdir()
    return SimpleNamespace(tmp=tmp_path, bin=bindir, temp=temp, models=models, home=home)


def _model(env, name: str, *, config: bool = True) -> None:
    (env.models / f"{name}.onnx").write_bytes(b"onnx")
    if config:
        (env.models / f"{name}.onnx.json").write_text("{}", encoding="utf-8")


def _piper(env, *models: str) -> Path:
    exe = _fake(env.bin / "piper", env.tmp)
    for name in models:
        _model(env, name)
    assert settings_db.put_category("voice", {"piper_model_dir": str(env.models)}) == (1, [])
    return exe


def _run_dirs(env) -> list[Path]:
    return sorted(env.temp.glob("run-*")) if env.temp.exists() else []


def _engine(**kw) -> TTSEngine:
    return TTSEngine(**kw)


async def _edge_stub(text, voice):
    return f"edge:{voice}"


# ── Piper ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_piper_voice_invokes_piper_argv(env, monkeypatch):
    exe = _piper(env, "ro_RO-test-medium")
    engine = _engine()
    path = await engine.speak("Bună ziua, lume.", voice="piper:ro_RO-test-medium", lang="ro")
    [rec] = _records(env.tmp)
    model = (env.models / "ro_RO-test-medium.onnx").resolve()
    assert rec["argv"][:6] == [str(exe.resolve()), "--model", str(model), "--config", f"{model}.json",
                               "--output_file"]
    out = Path(rec["argv"][6])
    assert out.name == "out.wav" and out.parent.parent == env.temp and out.parent.name.startswith("run-")
    assert rec["stdin"] == "Bună ziua, lume.\n"
    assert path and Path(path).parent == env.temp and path.endswith(".wav")
    assert Path(path).read_bytes() == WAV
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert _run_dirs(env) == []                      # the run directory is gone


@pytest.mark.asyncio
async def test_piper_package_preferred_when_importable(env, monkeypatch):
    _piper(env, "en_US-amy-low")
    calls = []

    class FakeVoice:
        @classmethod
        def load(cls, model, config_path=None):
            calls.append(("load", model, config_path))
            return cls()

        def synthesize_wav(self, text, wav_file):
            calls.append(("synth", text))
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(b"\0\0" * 10)

    monkeypatch.setattr(lp, "_import_piper", lambda: FakeVoice)
    path = await _engine().speak("Hello there.", voice="piper:en_US-amy-low", lang="en")
    assert path and path.endswith(".wav") and Path(path).read_bytes()[:4] == b"RIFF"
    assert calls[0][0] == "load" and calls[-1] == ("synth", "Hello there.")
    assert _records(env.tmp) == []                   # the binary never ran


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["../x", "a/b", "a\\b", "-rf", "..", "", "x" * 200, "a\x00b"])
async def test_piper_model_name_refused(env, monkeypatch, name):
    _piper(env, "en_US-amy-low")
    engine = _engine()
    edge = []

    async def fake_edge(text, voice):
        edge.append(voice)
        return "edge"

    monkeypatch.setattr(tts_module, "HAS_EDGE", True)
    monkeypatch.setattr(engine, "_speak_edge", fake_edge)
    if name == "":
        assert lp.resolve_piper_model(name) is None
        return
    assert await engine.speak("hello", voice=f"piper:{name}", lang="en") == "edge"
    assert edge == [engine._safe_default_voice("en")]
    assert _records(env.tmp) == []


@pytest.mark.asyncio
async def test_piper_model_symlink_out_of_dir_and_missing_config_refused(env, monkeypatch):
    _piper(env)
    outside = env.tmp / "outside"
    (outside / "evil.onnx").write_bytes(b"x")
    (outside / "evil.onnx.json").write_text("{}")
    (env.models / "evil.onnx").symlink_to(outside / "evil.onnx")
    (env.models / "evil.onnx.json").symlink_to(outside / "evil.onnx.json")
    _model(env, "noconf", config=False)
    assert lp.resolve_piper_model("evil") is None
    assert lp.resolve_piper_model("noconf") is None
    assert lp.list_piper_voices() == []
    engine = _engine()
    monkeypatch.setattr(tts_module, "HAS_EDGE", True)
    monkeypatch.setattr(engine, "_speak_edge", _edge_stub)
    assert (await engine.speak("hi", voice="piper:evil", lang="en")).startswith("edge:")
    assert _records(env.tmp) == []


@pytest.mark.asyncio
async def test_piper_timeout_kills_reaps_and_falls_back(env, monkeypatch):
    _piper(env, "en_US-amy-low")
    _mode(env.tmp, "sleep")
    monkeypatch.setattr(lp, "TTS_TIMEOUT_S", 0.5)
    engine = _engine()
    monkeypatch.setattr(tts_module, "HAS_EDGE", True)
    monkeypatch.setattr(engine, "_speak_edge", _edge_stub)
    start = time.monotonic()
    res = await engine.speak("hi", voice="piper:en_US-amy-low", lang="en")
    assert res == f"edge:{engine._safe_default_voice('en')}"
    assert time.monotonic() - start < 10
    [rec] = _records(env.tmp)
    with pytest.raises(ProcessLookupError):
        os.kill(rec["pid"], 0)
    assert _run_dirs(env) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["fail", "nonwav", "big", "empty", "symlink"])
async def test_piper_bad_run_or_output_falls_back(env, monkeypatch, mode):
    _piper(env, "en_US-amy-low")
    _mode(env.tmp, mode)
    engine = _engine()
    monkeypatch.setattr(tts_module, "HAS_EDGE", True)
    monkeypatch.setattr(engine, "_speak_edge", _edge_stub)
    res = await engine.speak("hi", voice="piper:en_US-amy-low", lang="en")
    assert res.startswith("edge:")
    assert [p.name for p in env.temp.glob("response_*")] == []
    assert _run_dirs(env) == []


@pytest.mark.asyncio
async def test_piper_multiline_text_sent_as_one_line_and_tags_stripped(env):
    _piper(env, "en_US-amy-low")
    await _engine().speak("[calm] **Hi** there.\nSecond   line.", voice="piper:en_US-amy-low", lang="en")
    [rec] = _records(env.tmp)
    assert rec["stdin"].count("\n") == 1 and rec["stdin"].endswith("\n")
    assert "[calm]" not in rec["stdin"] and "**" not in rec["stdin"]
    assert "Hi there." in rec["stdin"] and "Second line." in rec["stdin"]


@pytest.mark.asyncio
async def test_local_only_tries_piper_before_edge_and_never_calls_edge(env, monkeypatch):
    _piper(env, "en_US-amy-low", "ro_RO-mihai-medium")
    settings_db.put_category("voice", {"local_only": True})
    engine = _engine()
    edge = []

    async def fake_edge(text, voice):
        edge.append(voice)
        return "edge"

    monkeypatch.setattr(tts_module, "HAS_EDGE", True)
    monkeypatch.setattr(engine, "_speak_edge", fake_edge)
    path = await engine.speak("Salut", lang="ro")
    assert path and path.endswith(".wav")
    [rec] = _records(env.tmp)
    assert rec["argv"][2].endswith("ro_RO-mihai-medium.onnx")
    # no Piper model: kokoro, else nothing — edge is never called
    for f in env.models.iterdir():
        f.unlink()
    monkeypatch.setattr(tts_module, "HAS_KOKORO", False)
    assert await engine.speak("Salut", lang="ro") is None
    kokoro = []

    async def fake_kokoro(text, voice):
        kokoro.append(voice)
        return "kokoro"

    monkeypatch.setattr(tts_module, "HAS_KOKORO", True)
    monkeypatch.setattr(engine, "_speak_kokoro", fake_kokoro)
    assert await engine.speak("Salut", lang="ro") == "kokoro"
    assert edge == []


@pytest.mark.asyncio
async def test_local_only_skips_elevenlabs_and_fish_even_with_consent(env, monkeypatch):
    _piper(env, "en_US-amy-low")
    settings_db.put_category("voice", {"local_only": True})
    engine = _engine(consent_getter=lambda: True)
    called = []

    async def cloud(text, voice):
        called.append(voice)
        return "cloud"

    monkeypatch.setattr(engine, "_speak_elevenlabs", cloud)
    monkeypatch.setattr(engine, "_speak_fish", cloud)
    monkeypatch.setattr(engine, "_speak_edge", cloud)
    monkeypatch.setattr(tts_module, "HAS_EDGE", True)
    for voice in ("elevenlabs:abc", "fish:ref", "fish"):
        path = await engine.speak("hello", voice=voice, lang="en")
        assert path and path.endswith(".wav"), voice
    assert called == []


@pytest.mark.asyncio
async def test_fish_named_piper_model_goes_to_piper_after_consent_gate_unchanged(env, monkeypatch):
    _piper(env, "en_US-fishy")
    fish = []

    async def fake_fish(text, voice):
        fish.append(voice)
        return "fish"

    allowed = _engine(consent_getter=lambda: True)
    monkeypatch.setattr(allowed, "_speak_fish", fake_fish)
    path = await allowed.speak("hello", voice="piper:en_US-fishy", lang="en")
    assert path and path.endswith(".wav") and fish == []
    assert allowed.last_consent_status["required"] is True
    blocked = _engine(consent_getter=lambda: False)
    monkeypatch.setattr(blocked, "_speak_fish", fake_fish)
    monkeypatch.setattr(tts_module, "HAS_EDGE", True)
    monkeypatch.setattr(blocked, "_speak_edge", _edge_stub)
    assert await blocked.speak("hello", voice="piper:en_US-fishy", lang="en") == \
        f"edge:{blocked._safe_default_voice('en')}"
    assert len(_records(env.tmp)) == 1 and fish == []


@pytest.mark.asyncio
async def test_piper_and_command_voices_are_not_persona_markers(env):
    _piper(env, "en_US-amy-low")
    engine = _engine(consent_getter=lambda: False)
    await engine.speak("hello", voice="piper:en_US-amy-low", lang="en")
    assert engine.last_consent_status["required"] is False
    assert tts_module.PERSONA_VOICE_MARKERS == ("xtts", "elevenlabs", "fish")
    assert not tts_module.is_persona_or_cloned_voice("piper:en_US-amy-low")
    assert not tts_module.is_persona_or_cloned_voice("command")


@pytest.mark.asyncio
async def test_xtts_without_consent_never_reaches_xtts(env, monkeypatch):
    engine = _engine(consent_getter=lambda: False)
    xtts = []

    async def fake_xtts(text, voice):
        xtts.append(voice)
        return "xtts"

    monkeypatch.setattr(engine, "_speak_xtts", fake_xtts)
    monkeypatch.setattr(tts_module, "HAS_EDGE", True)
    monkeypatch.setattr(engine, "_speak_edge", _edge_stub)
    assert (await engine.speak("hello", voice="xtts", lang="en")).startswith("edge:")
    assert xtts == [] and engine.last_consent_status["required"] is True


@pytest.mark.asyncio
async def test_piper_binary_off_in_safe_mode_package_still_on(env, monkeypatch):
    _piper(env, "en_US-amy-low")
    monkeypatch.setenv("JARVIS_SAFE_MODE", "1")
    assert lp.piper_backend() is None
    engine = _engine()
    monkeypatch.setattr(tts_module, "HAS_EDGE", True)
    monkeypatch.setattr(engine, "_speak_edge", _edge_stub)
    assert (await engine.speak("hi", voice="piper:en_US-amy-low", lang="en")).startswith("edge:")
    assert _records(env.tmp) == []

    class FakeVoice:
        @classmethod
        def load(cls, model, config_path=None):
            return cls()

        def synthesize(self, text, wav_file):              # the piper-tts 1.2 spelling
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(b"\0\0")

    monkeypatch.setattr(lp, "_import_piper", lambda: FakeVoice)
    assert lp.piper_backend()[0] == "package"
    assert (await engine.speak("hi", voice="piper:en_US-amy-low", lang="en")).endswith(".wav")


def test_piper_model_dir_setting_is_validated(env):
    assert settings_db.validate_category("voice", {"piper_model_dir": ""}) == []
    assert settings_db.validate_category("voice", {"piper_model_dir": str(env.models)}) == []
    assert settings_db.validate_category("voice", {"piper_model_dir": "relative/dir"})
    assert settings_db.validate_category("voice", {"piper_model_dir": str(env.tmp / "missing")})
    assert settings_db.validate_category("voice", {"stt_engine": "command"}) == []
    assert settings_db.validate_category("voice", {"stt_engine": "shell"})
    assert settings_db.validate_category("voice", {"local_only": "yes"})


# ── Command TTS ───────────────────────────────────────────────────────────────────────

def _tts_argv(exe: Path) -> list[str]:
    return [str(exe), "--lang", "{lang}", "--in", "{text_file}", "--out", "{output}"]


def _stt_argv(exe: Path) -> list[str]:
    return [str(exe), "--audio", "{audio}", "--lang", "{lang}"]


async def _approve(env, side: str, argv: list[str]) -> dict:
    """Request, then a human accepts: the stored value the route's approval writes."""
    problems, exe = lp.validate_command(argv, side)
    assert problems == [], problems
    task = SimpleNamespace(
        id=7, kind=command_settings.APPROVAL_KIND, decided_by="owner", decision="accept",
        payload={"side": side, "argv": argv, "fingerprint": command_settings._fingerprint(argv),
                 "exe_identity": lp.exe_identity(exe),
                 "before_fingerprint": lp.stored_command(side).get("fingerprint")})
    return await irreversible.execute(task, orch=None)


@pytest.fixture
def armed(env, monkeypatch):
    monkeypatch.setenv("JARVIS_VOICE_COMMANDS", "1")
    return env


@pytest.mark.asyncio
async def test_command_tts_happy_path(armed, monkeypatch):
    env = armed
    exe = _fake(env.tmp / "opt" / "say-wav", env.tmp)
    assert (await _approve(env, "tts", _tts_argv(exe)))["status"] == "ok"
    path = await _engine().speak("Salut, lume.", voice="command", lang="ro")
    [rec] = _records(env.tmp)
    assert rec["argv"][0] == str(exe.resolve())
    assert rec["argv"][1:3] == ["--lang", "ro"]
    text_file, out = Path(rec["argv"][4]), Path(rec["argv"][6])
    assert text_file.parent == out.parent and out.parent.parent == env.temp
    assert rec["text_file"] == "Salut, lume." and rec["text_file_mode"] == "0o600"
    assert rec["stdin"] == ""
    assert path and Path(path).parent == env.temp and path.endswith(".wav")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert _run_dirs(env) == []


@pytest.mark.asyncio
async def test_command_text_never_in_argv_or_a_shell(armed, monkeypatch):
    env = armed
    exe = _fake(env.tmp / "opt" / "say-wav", env.tmp)
    argv = [str(exe), "--out", "{output}"]                     # text on stdin
    await _approve(env, "tts", argv)
    spawned = []
    real = lp._spawn

    async def spy(*args, **kwargs):
        spawned.append((args, kwargs))
        return await real(*args, **kwargs)

    monkeypatch.setattr(lp, "_spawn", spy)
    evil = "'; touch pwned $(touch pwned2) `id`"
    path = await _engine().speak(evil, voice="command", lang="en")
    assert path
    [(args, kwargs)] = spawned
    assert args[0] == str(exe.resolve()) and "shell" not in kwargs
    assert not any("pwned" in a or "touch" in a for a in args)
    [rec] = _records(env.tmp)
    assert "pwned" in rec["stdin"]
    assert not list(env.tmp.rglob("pwned*")) and not list(Path.cwd().glob("pwned*"))


@pytest.mark.asyncio
async def test_command_voice_suffix_never_enters_argv(armed):
    env = armed
    exe = _fake(env.tmp / "opt" / "say-wav", env.tmp)
    await _approve(env, "tts", _tts_argv(exe))
    await _engine().speak("hello", voice="command:/bin/sh -c id", lang="en")
    [rec] = _records(env.tmp)
    assert rec["argv"][0] == str(exe.resolve())
    assert len(rec["argv"]) == 7 and "/bin/sh" not in rec["argv"] and "-c" not in rec["argv"]


@pytest.mark.asyncio
@pytest.mark.parametrize("lang", ["en; id", "--x", "../", None])
async def test_command_lang_is_validated(armed, lang):
    env = armed
    exe = _fake(env.tmp / "opt" / "say-wav", env.tmp)
    await _approve(env, "tts", _tts_argv(exe))
    await _engine(default_lang="en").speak("hello", voice="command", lang=lang)
    [rec] = _records(env.tmp)
    assert rec["argv"][2] == "en"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sleep", "fail", "symlink", "big", "nonwav", "empty"])
async def test_command_bad_run_or_output_falls_back(armed, monkeypatch, mode):
    env = armed
    exe = _fake(env.tmp / "opt" / "say-wav", env.tmp)
    await _approve(env, "tts", _tts_argv(exe))
    _mode(env.tmp, mode)
    monkeypatch.setattr(lp, "TTS_TIMEOUT_S", 0.5)
    engine = _engine()
    monkeypatch.setattr(tts_module, "HAS_EDGE", True)
    monkeypatch.setattr(engine, "_speak_edge", _edge_stub)
    assert (await engine.speak("hello", voice="command", lang="en")).startswith("edge:")
    [rec] = _records(env.tmp)
    if mode == "sleep":
        with pytest.raises(ProcessLookupError):
            os.kill(rec["pid"], 0)
    assert list(env.temp.glob("response_*")) == []
    assert _run_dirs(env) == []


@pytest.mark.asyncio
async def test_command_stdout_flood_is_capped(armed, monkeypatch):
    env = armed
    exe = _fake(env.tmp / "opt" / "say-wav", env.tmp)
    await _approve(env, "tts", _tts_argv(exe))
    ready = lp.command_ready("tts")
    _mode(env.tmp, "flood")
    workdir = env.tmp / "wd"
    workdir.mkdir()
    start = time.monotonic()
    run = await lp.run_bounded([str(ready.exe), "--out", str(workdir / "o.wav")], cwd=workdir,
                               stdin_bytes=b"x", timeout=20)
    assert run["ok"] and time.monotonic() - start < 20
    assert len(run["stdout"]) <= lp.MAX_STREAM_BYTES


@pytest.mark.asyncio
async def test_command_not_run_when_unarmed_safe_mode_changed_removed_or_world_writable(armed, monkeypatch):
    env = armed
    exe = _fake(env.tmp / "opt" / "say-wav", env.tmp)
    await _approve(env, "tts", _tts_argv(exe))
    engine = _engine()
    monkeypatch.setattr(tts_module, "HAS_EDGE", True)
    monkeypatch.setattr(engine, "_speak_edge", _edge_stub)

    async def spoke() -> bool:
        before = len(_records(env.tmp))
        await engine.speak("hello", voice="command", lang="en")
        return len(_records(env.tmp)) > before

    assert await spoke()
    monkeypatch.delenv("JARVIS_VOICE_COMMANDS")
    assert lp.command_ready("tts").reason == lp.NOT_ARMED and not await spoke()
    monkeypatch.setenv("JARVIS_VOICE_COMMANDS", "1")
    monkeypatch.setenv("JARVIS_SAFE_MODE", "1")
    assert lp.command_ready("tts").reason == lp.SAFE_MODE and not await spoke()
    monkeypatch.delenv("JARVIS_SAFE_MODE")
    exe.chmod(0o757)
    assert lp.command_ready("tts").reason == lp.INVALID and not await spoke()
    exe.chmod(0o755)
    assert await spoke()
    exe.write_text(exe.read_text() + "\n# upgraded\n")
    assert lp.command_ready("tts").reason == lp.CHANGED_SINCE_APPROVAL and not await spoke()
    exe.unlink()
    assert lp.command_ready("tts").reason == lp.EXE_MISSING and not await spoke()


# ── Command STT ───────────────────────────────────────────────────────────────────────

OGG = b"OggS" + b"\0" * 60


@pytest.mark.asyncio
async def test_stt_command_used_when_whisper_absent(armed, monkeypatch):
    env = armed
    exe = _fake(env.tmp / "opt" / "stt", env.tmp, no_stdin=True)
    await _approve(env, "stt", _stt_argv(exe))
    monkeypatch.setattr(stt_module, "HAS_WHISPER", False)
    engine = stt_module.STTEngine()
    assert await engine.transcribe_async(OGG, language="ro") == "salut lume"
    [rec] = _records(env.tmp)
    audio = Path(rec["argv"][2])
    assert audio.name == "audio.ogg" and audio.parent.parent == env.temp
    assert rec["audio"] == OGG.hex() and rec["audio_mode"] == "0o600" and rec["run_dir_mode"] == "0o700"
    assert rec["argv"][4] == "ro"
    assert not audio.exists() and _run_dirs(env) == []


@pytest.mark.asyncio
async def test_stt_path_input_is_copied_into_the_run_dir(armed, monkeypatch):
    env = armed
    exe = _fake(env.tmp / "opt" / "stt", env.tmp, no_stdin=True)
    await _approve(env, "stt", _stt_argv(exe))
    monkeypatch.setattr(stt_module, "HAS_WHISPER", False)
    src = env.tmp / "note.ogg"
    src.write_bytes(OGG)
    assert await stt_module.STTEngine().transcribe_async(str(src), language="en") == "salut lume"
    [rec] = _records(env.tmp)
    assert Path(rec["argv"][2]).parent.parent == env.temp and src.exists()


@pytest.mark.asyncio
async def test_stt_engine_setting_command_whisper_auto(armed, monkeypatch):
    env = armed
    exe = _fake(env.tmp / "opt" / "stt", env.tmp, no_stdin=True)
    await _approve(env, "stt", _stt_argv(exe))
    engine = stt_module.STTEngine.__new__(stt_module.STTEngine)
    engine.model_size, engine.device, engine.beam_size = "tiny", "cpu", 1
    whisper = []

    class FakeModel:
        def transcribe(self, *a, **kw):
            whisper.append(1)
            return [SimpleNamespace(text="from whisper")], SimpleNamespace(duration=3.0)

    engine._model = FakeModel()
    assert await engine.transcribe_async(OGG, language="en") == "from whisper"      # auto + whisper
    settings_db.put_category("voice", {"stt_engine": "command"})
    assert await engine.transcribe_async(OGG, language="en") == "salut lume"
    settings_db.put_category("voice", {"stt_engine": "whisper"})
    engine._model = None
    assert await engine.transcribe_async(OGG, language="en") == "[STT unavailable]"
    assert len(_records(env.tmp)) == 1 and whisper == [1]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,expected", [("fail", "[STT error: command exited 3]"),
                                           ("sleep", "[STT error: command timed out]"),
                                           ("silent", "[silence]"), ("hallucinate", "[silence]")])
async def test_stt_command_sentinels(armed, monkeypatch, mode, expected):
    env = armed
    exe = _fake(env.tmp / "opt" / "stt", env.tmp, no_stdin=True)
    await _approve(env, "stt", _stt_argv(exe))
    monkeypatch.setattr(stt_module, "HAS_WHISPER", False)
    monkeypatch.setattr(lp, "STT_TIMEOUT_S", 0.5)
    _mode(env.tmp, mode)
    assert await stt_module.STTEngine().transcribe_async(OGG, language="en") == expected


def test_stt_sync_transcribe_command_path(armed, monkeypatch):
    env = armed
    exe = _fake(env.tmp / "opt" / "stt", env.tmp, no_stdin=True)
    asyncio.run(_approve(env, "stt", _stt_argv(exe)))
    monkeypatch.setattr(stt_module, "HAS_WHISPER", False)
    assert stt_module.STTEngine().transcribe(OGG, language="en") == "salut lume"

    async def inside_a_loop():
        return stt_module.STTEngine().transcribe(OGG, language="en")

    assert asyncio.run(inside_a_loop()) == "[STT error: command STT needs an async caller]"


def test_stt_unavailable_without_whisper_or_command(env, monkeypatch):
    monkeypatch.setattr(stt_module, "HAS_WHISPER", False)
    assert stt_module.STTEngine().transcribe(OGG, language="en") == "[STT unavailable]"


# ── validation ────────────────────────────────────────────────────────────────────────

def _bad_argvs(env) -> list[tuple[str, list, str]]:
    exe = _fake(env.tmp / "opt" / "prog", env.tmp)
    plain = env.tmp / "opt" / "plain"
    plain.write_text("x")
    plain.chmod(0o644)
    script = env.tmp / "opt" / "s.py"
    script.write_text("print(1)")
    e = str(exe)
    return [
        ("relative program", ["prog", "{output}"], "absolute"),
        ("missing program", [str(env.tmp / "nope"), "{output}"], "does not exist"),
        ("a directory", [str(env.tmp / "opt"), "{output}"], "not a regular file"),
        ("not executable", [str(plain), "{output}"], "not executable"),
        ("placeholder as program", ["{output}"], "placeholder"),
        ("placeholder inside program", ["/opt/{x}/bin", "{output}"], "placeholder"),
        ("unknown placeholder", [e, "{home}", "{output}"], "embedded_or_unknown_placeholder"),
        ("embedded placeholder", [e, "--out={output}"], "embedded_or_unknown_placeholder"),
        ("sh", ["/bin/sh", "-c", "id", "{output}"], "launcher"),
        ("bash", [os.path.realpath("/bin/bash"), "{output}"], "launcher"),
        ("env", ["/usr/bin/env", "{output}"], "launcher"),
        ("python -c", [sys.executable, "-c", "print(1)", "{output}"], "interpreter"),
        ("NUL", [e, "a\x00b", "{output}"], "NUL"),
        ("65 items", [e, "{output}"] + ["x"] * 63, "1 to 64"),
        ("4001 chars", [e, "{output}", "x" * 4001], "longer than"),
        ("credential", [e, "{output}", "--key", "sk-ant-api03-" + "A" * 40], "visible to every process"),
        ("hardline", [e, "{output}", ":(){ :|:& };:"], "hardline"),
        ("tts without output", [e, "{text_file}"], "{output} must appear exactly once"),
        ("duplicate output", [e, "{output}", "{output}"], "{output} must appear exactly once"),
        ("audio on tts", [e, "{output}", "{audio}"], "not a tts placeholder"),
    ] + [("python script ok", [sys.executable, str(script), "{output}"], "")]


def test_validate_command_refusals(env):
    for label, argv, needle in _bad_argvs(env):
        problems, exe = lp.validate_command(argv, "tts")
        if not needle:
            assert problems == [] and exe is not None, (label, problems)
            continue
        assert problems and exe is None, label
        assert any(needle in p for p in problems), (label, problems)
    exe = str(_fake(env.tmp / "opt" / "prog", env.tmp))
    assert any("{audio} must appear exactly once" in p for p in lp.validate_command([exe, "{lang}"], "stt")[0])
    assert lp.validate_command([exe, "{audio}", "{lang}", "{lang}"], "stt")[0] == []
    assert lp.validate_command([exe, "{audio}"], "shell")[0]


# ── governance: the only writer ───────────────────────────────────────────────────────

@pytest.fixture
def orch(env, tmp_path):
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.autonomy.queue import TaskQueue
    from agents.core.autonomy.worker import AutonomyWorker, InterruptBudget
    from agents.core.security.audit import AuditLogger

    audit = AuditLogger(db_path=str(tmp_path / "audit.db"))
    queue = TaskQueue(db_path=str(tmp_path / "autonomy.db")).initialize()
    worker = AutonomyWorker(queue, policy=AutonomyPolicy(cap_per_action=50, daily_ceiling=200),
                            budget=InterruptBudget(per_day=4))
    intents = []
    intent_log = SimpleNamespace(record=lambda **kw: intents.append(kw))
    yield SimpleNamespace(autonomy=worker, audit=audit, queue=queue, intent_log=intent_log, intents=intents)
    queue.close()


@pytest.fixture
def client(env, orch, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import voice as voice_router

    monkeypatch.setattr(web, "ADMIN_TOKEN", "adm-h613")
    monkeypatch.setattr(voice_router, "get_orch", lambda: orch)
    return TestClient(web.app)


def _audit_rows(orch) -> list[str]:
    from agents.core.security.types import SecurityEventType

    return [e.content_preview for e in orch.audit.query(limit=100)
            if e.event_type == SecurityEventType.SETTINGS_CHANGE]


def _pending(orch) -> list:
    return [t for t in orch.queue.pending_decisions() if t.kind == command_settings.APPROVAL_KIND]


def test_generic_writers_refuse_voice_commands(armed, monkeypatch, capsys):
    env = armed
    exe = _fake(env.tmp / "opt" / "say-wav", env.tmp)
    value = {"argv": _tts_argv(exe), "exe": lp.exe_identity(exe.resolve()),
             "fingerprint": command_settings._fingerprint(_tts_argv(exe))}
    for key in ("tts_command", "stt_command"):
        assert ("voice", key) in settings_db.ROUTE_ONLY
        assert "POST /api/admin/voice/commands" in settings_db.ROUTE_ONLY[("voice", key)]
        assert settings_db.route_only_problems("voice", [key])
    # import
    changes, errors = settings_db.plan_import({"settings": {"voice": {"tts_command": value}}})
    assert changes == {} and errors and "/api/admin/voice/commands" in errors[0]
    # export leaves them out
    doc = settings_db.export_settings()
    assert "tts_command" not in doc["settings"].get("voice", {})
    # nerva config set
    from agents.cli import nerva

    code = nerva.main(["config", "set", "voice.tts_command", json.dumps(value)])
    err = capsys.readouterr().err
    assert code != 0 and "/api/admin/voice/commands" in err and "skill switch" not in err
    # reset keeps, undo does not restore
    asyncio.run(_approve(env, "tts", _tts_argv(exe)))
    stored = lp.stored_command("tts")
    assert stored["argv"]
    settings_db.reset_settings("voice")
    settings_db.reset_settings(None)
    assert lp.stored_command("tts") == stored
    assert "voice.tts_command" in settings_db.reset_kept_all()


def test_undo_reset_never_restores_a_route_only_row(env):
    conn = settings_db.get_conn()
    with conn:
        conn.execute("INSERT INTO settings_resets (at, scope, before, after) VALUES (?,?,?,?)",
                     (time.time(), "voice", json.dumps({"voice": {"tts_command": {"argv": ["/x", "{output}"]}}}),
                      json.dumps({"voice": {"tts_command": {}}})))
    conn.close()
    done = settings_db.undo_last_reset()
    assert "voice.tts_command" not in done["restored"]
    assert lp.stored_command("tts") == {}


def test_admin_put_refuses_voice_commands(client):
    resp = client.put("/api/admin/settings/voice", headers=ADMIN,
                      json={"values": {"tts_command": {"argv": ["/bin/true", "{output}"]}}})
    assert resp.status_code == 422 and "/api/admin/voice/commands" in resp.text


def test_command_route_admin_only_and_same_origin(client):
    body = {"side": "tts", "argv": ["/bin/true", "{output}"]}
    assert client.post("/api/admin/voice/commands", json=body).status_code in (401, 403)
    assert client.get("/api/admin/voice/commands").status_code in (401, 403)
    resp = client.post("/api/admin/voice/commands", headers={**ADMIN, "content-type": "text/plain"},
                       content=json.dumps(body))
    assert resp.status_code == 415
    resp = client.post("/api/admin/voice/commands", headers={**ADMIN, "sec-fetch-site": "cross-site"}, json=body)
    assert resp.status_code == 403
    huge = {"side": "tts", "argv": ["/bin/true", "{output}", "x" * 400_000]}
    assert client.post("/api/admin/voice/commands", headers=ADMIN, json=huge).status_code == 413


def test_command_route_set_enqueues_and_writes_nothing(armed, client, orch):
    env = armed
    exe = _fake(env.tmp / "opt" / "say-wav", env.tmp)
    argv = _tts_argv(exe)
    resp = client.post("/api/admin/voice/commands", headers=ADMIN, json={"side": "tts", "argv": argv})
    assert resp.status_code == 202, resp.text
    task_id = resp.json()["pending"]
    assert lp.stored_command("tts") == {}
    [task] = _pending(orch)
    assert task.id == task_id and task.risk_tier == 3 and task.payload["reversible"] is False
    preview = task.payload["preview"]
    assert preview["program"] == str(exe.resolve()) and preview["argv"] == argv and preview["side"] == "tts"
    assert preview["runs_as"] and preview["timeout_s"] == lp.TTS_TIMEOUT_S
    again = client.post("/api/admin/voice/commands", headers=ADMIN, json={"side": "tts", "argv": argv})
    assert again.status_code == 202 and again.json()["pending"] == task_id and len(_pending(orch)) == 1
    other = client.post("/api/admin/voice/commands", headers=ADMIN,
                        json={"side": "tts", "argv": argv + ["--quiet"]})
    assert other.status_code == 409 and other.json()["error"] == "request_waiting"
    dry = client.post("/api/admin/voice/commands", headers=ADMIN,
                      json={"side": "stt", "argv": _stt_argv(exe), "dry_run": True})
    assert dry.status_code == 200 and dry.json()["exe"] == str(exe.resolve())
    fp = task.payload["fingerprint"][:16]
    assert any("sent to approval" in row and "program say-wav" in row and fp in row for row in _audit_rows(orch))
    state = client.get("/api/admin/voice/commands", headers=ADMIN).json()
    assert state["sides"]["tts"]["pending_task"] == task_id and state["sides"]["tts"]["configured"] is False


def test_command_route_refuses_unarmed_safe_mode_invalid(env, client, orch, monkeypatch):
    exe = _fake(env.tmp / "opt" / "say-wav", env.tmp)
    body = {"side": "tts", "argv": _tts_argv(exe)}
    resp = client.post("/api/admin/voice/commands", headers=ADMIN, json=body)
    assert resp.status_code == 409 and resp.json()["error"] == "not_armed"
    monkeypatch.setenv("JARVIS_VOICE_COMMANDS", "1")
    monkeypatch.setenv("JARVIS_SAFE_MODE", "1")
    resp = client.post("/api/admin/voice/commands", headers=ADMIN, json=body)
    assert resp.status_code == 409 and resp.json()["error"] == "safe_mode"
    monkeypatch.delenv("JARVIS_SAFE_MODE")
    resp = client.post("/api/admin/voice/commands", headers=ADMIN, json={"side": "tts", "argv": ["/bin/sh", "{output}"]})
    assert resp.status_code == 422 and resp.json()["problems"]
    resp = client.post("/api/admin/voice/commands", headers=ADMIN, json={"side": "both", "argv": _tts_argv(exe)})
    assert resp.status_code == 422
    assert _pending(orch) == [] and lp.stored_command("tts") == {}


def test_queue_refusal_is_503_and_writes_nothing(armed, client, orch, monkeypatch):
    env = armed
    exe = _fake(env.tmp / "opt" / "say-wav", env.tmp)

    def refuse(**kw):
        raise RuntimeError("mediation enforce")

    monkeypatch.setattr(orch.autonomy, "govern_enqueue", refuse)
    resp = client.post("/api/admin/voice/commands", headers=ADMIN, json={"side": "tts", "argv": _tts_argv(exe)})
    assert resp.status_code == 503 and resp.json()["error"] == "approval_unavailable"
    assert lp.stored_command("tts") == {}


@pytest.mark.asyncio
async def test_apply_approved_only_on_human_accept(armed, orch):
    env = armed
    exe = _fake(env.tmp / "opt" / "say-wav", env.tmp)
    argv = _tts_argv(exe)
    status, body = await command_settings.request(orch, "tts", argv)
    assert status == 202
    [task] = _pending(orch)

    def decided(**kw):
        return SimpleNamespace(id=task.id, kind=task.kind, payload=task.payload, **kw)

    assert (await irreversible.execute(decided(decided_by="policy", decision="accept"), orch=orch))["reason"] == \
        "human_decision_required"
    assert (await irreversible.execute(decided(decided_by="owner", decision="edit"), orch=orch))["reason"] == \
        "edit_not_supported"
    assert lp.stored_command("tts") == {}
    done = await irreversible.execute(decided(decided_by="owner", decision="accept"), orch=orch)
    assert done["status"] == "ok"
    stored = lp.stored_command("tts")
    assert stored["argv"] == argv and stored["approved_task"] == task.id
    assert stored["exe"] == lp.exe_identity(exe.resolve()) and stored["fingerprint"] == task.payload["fingerprint"]
    assert any("approved" in row and stored["fingerprint"][:16] in row and "program say-wav" in row
               for row in _audit_rows(orch))
    assert orch.intents and orch.intents[-1]["action"] == "voice.command.set"
    assert lp.command_ready("tts").ok


@pytest.mark.asyncio
async def test_apply_refuses_when_exe_or_stored_value_changed_since_request(armed, orch):
    env = armed
    exe = _fake(env.tmp / "opt" / "say-wav", env.tmp)
    argv = _tts_argv(exe)
    await command_settings.request(orch, "tts", argv)
    [task] = _pending(orch)
    accept = SimpleNamespace(id=task.id, kind=task.kind, payload=task.payload, decided_by="owner", decision="accept")
    exe.write_text(exe.read_text() + "\n# swapped\n")
    assert (await irreversible.execute(accept, orch=orch))["reason"] == "changed_since_request"
    assert lp.stored_command("tts") == {}
    exe2 = _fake(env.tmp / "opt2" / "other", env.tmp)
    await command_settings.request(orch, "stt", _stt_argv(exe2))
    [stt_task] = [t for t in _pending(orch) if t.payload["side"] == "stt"]
    await _approve(env, "stt", _stt_argv(exe2) + ["--beam", "1"])   # the value moved meanwhile
    accept = SimpleNamespace(id=stt_task.id, kind=stt_task.kind, payload=stt_task.payload, decided_by="owner",
                             decision="accept")
    assert (await irreversible.execute(accept, orch=orch))["reason"] == "changed_since_request"


def test_command_route_clear_is_immediate_and_audited(armed, client, orch, monkeypatch):
    env = armed
    exe = _fake(env.tmp / "opt" / "say-wav", env.tmp)
    asyncio.run(_approve(env, "tts", _tts_argv(exe)))
    monkeypatch.delenv("JARVIS_VOICE_COMMANDS")                    # clearing needs nothing armed
    monkeypatch.setattr(orch.autonomy, "govern_enqueue", None)
    resp = client.post("/api/admin/voice/commands", headers=ADMIN, json={"side": "tts", "argv": None})
    assert resp.status_code == 200 and resp.json()["cleared"] is True
    assert lp.stored_command("tts") == {}
    assert any("voice.tts_command cleared" in row for row in _audit_rows(orch))
    assert orch.intents[-1]["action"] == "voice.command.clear"


def test_the_approval_kind_is_wired_to_the_irreversible_tier():
    assert command_settings.APPROVAL_KIND in irreversible.kinds()
    assert irreversible.BUILTIN_KINDS[command_settings.APPROVAL_KIND] == \
        ("agents.core.voice.command_settings", "apply_approved")


def test_no_other_module_writes_voice_command_keys():
    root = Path(__file__).resolve().parents[1] / "agents"
    import re

    call = re.compile(r"put_category\b[^\n]*(tts_command|stt_command|KEYS\[)")
    writers = []
    for path in root.rglob("*.py"):
        if call.search(path.read_text(encoding="utf-8", errors="replace")):
            writers.append(path.relative_to(root).as_posix())
    assert writers == ["core/voice/command_settings.py"]


# ── surfaces ──────────────────────────────────────────────────────────────────────────

def test_tts_route_serves_piper_wav_without_edge(env, client, monkeypatch):
    import core.voice.local_providers as core_lp
    import core.voice.tts as core_tts

    _piper(env, "en_US-amy-low")
    monkeypatch.setattr(core_tts, "HAS_EDGE", False)
    monkeypatch.setattr(core_tts, "HAS_KOKORO", False)
    monkeypatch.setattr(core_tts, "TEMP_DIR", env.temp)
    monkeypatch.setattr(core_lp, "_import_piper", lambda: None)
    resp = client.post("/tts", json={"text": "Hello", "lang": "en", "voice": "piper:en_US-amy-low"})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "audio/wav" and resp.content == WAV


def test_stt_route_uses_the_command_without_whisper(armed, client, monkeypatch):
    import core.voice.stt as core_stt

    from agents.core.routers import voice as voice_router

    env = armed
    exe = _fake(env.tmp / "opt" / "stt", env.tmp, no_stdin=True)
    asyncio.run(_approve(env, "stt", _stt_argv(exe)))
    monkeypatch.setattr(core_stt, "HAS_WHISPER", False)
    monkeypatch.setattr(core_stt, "TEMP_DIR", env.temp, raising=False)
    monkeypatch.setattr(voice_router, "_STT_ENGINE", None)
    resp = client.post("/api/voice/stt?lang=ro", content=OGG, headers={"content-type": "audio/ogg"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["text"] == "salut lume"


def test_capabilities_list_piper_and_command(armed, client, monkeypatch):
    env = armed
    _piper(env, "en_US-amy-low")
    import core.voice.local_providers as core_lp

    monkeypatch.setattr(core_lp, "_import_piper", lambda: None)
    exe = _fake(env.tmp / "opt" / "say-wav", env.tmp)
    asyncio.run(_approve(env, "tts", _tts_argv(exe)))
    caps = client.get("/api/voice/capabilities").json()
    providers = caps["providers"]
    assert providers["piper"] == {"available": True, "via": "binary", "voices": ["piper:en_US-amy-low"]}
    assert providers["command"]["tts"]["ready"] is True and providers["command"]["stt"]["configured"] is False
    assert caps["tts_local"] is True and "piper:en_US-amy-low" in caps["voices"] and "command" in caps["voices"]


def test_channels_and_tools_see_piper_and_the_stt_command(armed, monkeypatch):
    from agents.core.channels.inbound_voice import InboundVoiceReader as InboundVoice
    from agents.core.channels.spoken_reply import SpokenReply
    from agents.core.voice import speak_tool

    env = armed
    monkeypatch.setattr(tts_module, "HAS_EDGE", False)
    monkeypatch.setattr(tts_module, "HAS_KOKORO", False)
    monkeypatch.setattr(stt_module, "HAS_WHISPER", False)
    assert SpokenReply().is_available is False and InboundVoice().is_available is False
    assert speak_tool.tts_installed() is False
    _piper(env, "en_US-amy-low")
    assert SpokenReply().is_available is True and SpokenReply().backend_label() == "piper (local)"
    assert speak_tool.tts_installed() is True
    exe = _fake(env.tmp / "opt" / "stt", env.tmp, no_stdin=True)
    asyncio.run(_approve(env, "stt", _stt_argv(exe)))
    assert InboundVoice().is_available is True


def test_doctor_check_voice(monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import doctor

    def opener_for(payload):
        class Resp:
            def read(self):
                return json.dumps(payload).encode()

            def close(self):
                pass

        return lambda request, timeout=None: Resp()

    ok = doctor.Check("readyz", doctor.OK, "ok", "")
    good = {"stt": True, "tts": True, "providers": {
        "stt": "faster-whisper", "edge_tts": True, "kokoro": False,
        "piper": {"available": True, "via": "binary", "voices": ["piper:a", "piper:b"]},
        "command": {"tts": {"configured": True, "ready": True, "reason": None},
                    "stt": {"configured": False, "ready": False, "reason": "not_configured"}}}}
    check = doctor.check_voice(opener_for(good), readyz=ok, env={})
    assert check.status == doctor.OK and "piper(binary, 2 voices)" in check.detail and "command(ready)" in check.detail
    bad = json.loads(json.dumps(good))
    bad["providers"]["command"]["tts"] = {"configured": True, "ready": False, "reason": "changed_since_approval"}
    check = doctor.check_voice(opener_for(bad), readyz=ok, env={})
    assert check.status != doctor.OK and "changed_since_approval" in check.detail
    down = doctor.Check("readyz", doctor.WARN, "server_not_running", "")
    assert doctor.check_voice(opener_for(good), readyz=down, env={}).status == doctor.SKIP


def test_safe_mode_names_the_voice_layers():
    from agents.core import safe_mode

    assert "voice_commands" in safe_mode.LAYERS and "voice_piper_binary" in safe_mode.LAYERS


def test_flags_are_documented():
    root = Path(__file__).resolve().parents[1]
    example = (root / ".env.example").read_text(encoding="utf-8")
    flags = (root / "docs" / "FLAGS.md").read_text(encoding="utf-8")
    for name in ("JARVIS_VOICE_COMMANDS", "JARVIS_VOICE_COMMAND_TIMEOUT_S"):
        assert name in example and name in flags
