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


_TASK_IDS = iter(range(1000, 10**6))


def _queue_orch() -> SimpleNamespace:
    """An approval queue that takes every request (the real one is the ``orch`` fixture)."""
    tasks: dict[int, dict] = {}

    def govern_enqueue(**kw):
        task_id = next(_TASK_IDS)
        tasks[task_id] = kw
        return task_id

    worker = SimpleNamespace(govern_enqueue=govern_enqueue,
                             queue=SimpleNamespace(pending_decisions=lambda **kw: []))
    return SimpleNamespace(autonomy=worker, tasks=tasks)


async def _approve(env, side: str, argv: list[str]) -> dict:
    """Request (the card), then a human accepts it: the stored value the approval writes."""
    problems, exe = lp.validate_command(argv, side)
    assert problems == [], problems
    orch = _queue_orch()
    status, body = await command_settings.request(orch, side, argv)
    assert status == 202, body
    task = SimpleNamespace(id=body["pending"], kind=command_settings.APPROVAL_KIND, decided_by="owner",
                           decision="accept", payload=orch.tasks[body["pending"]]["payload"])
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
    value = {"argv": _tts_argv(exe), "exe": lp.exe_identity(exe.resolve()), "bound": [lp.exe_identity(exe.resolve())],
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
    resp = client.post("/api/admin/voice/commands", headers=ADMIN, json={"side": "tts", "clear": True})
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


# ── review round (h613_review F0..F20) ────────────────────────────────────────────────

PY_SAY = "import sys\nopen(sys.argv[1], 'wb').write({wav!r})\nopen({marker!r}, 'a').write({tag!r} + '\\n')\n"


def _script(env, body: str, *, parent: Path | None = None, name: str = "say.py") -> Path:
    folder = parent or (env.tmp / "scripts")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(body, encoding="utf-8")
    path.chmod(0o644)
    return path


def _alive(pid: int) -> bool:
    """Whether *pid* still runs (a zombie nobody reaps counts as gone)."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True
    return state not in ("Z", "X")


@pytest.mark.asyncio
@pytest.mark.parametrize("how", ["in_place", "replaced"])
async def test_f0_interpreter_script_is_bound_and_a_rewrite_needs_approving_again(armed, how):
    env = armed
    marker = env.tmp / "marker"
    script = _script(env, PY_SAY.format(wav=WAV, marker=str(marker), tag="good"))
    argv = [sys.executable, str(script), "{output}"]
    assert (await _approve(env, "tts", argv))["status"] == "ok"
    stored = lp.stored_command("tts")
    assert [b["path"] for b in stored["bound"]] == [str(Path(sys.executable).resolve()), str(script.resolve())]
    assert all(len(b["sha256"]) == 64 for b in stored["bound"])
    assert await lp.speak_command("hi", "en", temp_dir=env.temp)
    assert marker.read_text() == "good\n"
    evil = PY_SAY.format(wav=WAV, marker=str(marker), tag="EVIL")
    inode = script.stat().st_ino
    if how == "in_place":
        script.write_text(evil, encoding="utf-8")
        assert script.stat().st_ino == inode
    else:
        fresh = script.with_name("new.py")
        fresh.write_text(evil, encoding="utf-8")
        os.replace(fresh, script)
    assert lp.command_ready("tts").reason == lp.CHANGED_SINCE_APPROVAL
    assert await lp.speak_command("hi", "en", temp_dir=env.temp) is None
    assert "EVIL" not in marker.read_text()


@pytest.mark.asyncio
async def test_f4_in_place_rewrite_of_the_program_with_the_same_size_and_mtime(armed):
    env = armed
    exe = _fake(env.tmp / "opt" / "say-wav", env.tmp)
    await _approve(env, "tts", _tts_argv(exe))
    before = exe.stat()
    body = exe.read_bytes()
    evil = body.replace(b"salut lume", b"PWNED lume")
    assert len(evil) == len(body) and evil != body
    exe.write_bytes(evil)
    os.utime(exe, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = exe.stat()
    assert (after.st_ino, after.st_size, after.st_mtime_ns) == (before.st_ino, before.st_size, before.st_mtime_ns)
    assert lp.command_ready("tts").reason == lp.CHANGED_SINCE_APPROVAL


def test_f0_a_world_writable_script_or_script_dir_is_refused(env):
    ok = _script(env, "print(1)")
    assert lp.validate_command([sys.executable, str(ok), "{output}"], "tts")[0] == []
    loose = _script(env, "print(1)", name="loose.py")
    loose.chmod(0o666)
    problems = lp.validate_command([sys.executable, str(loose), "{output}"], "tts")[0]
    assert any(p.startswith("argv[1]") and "writable" in p for p in problems), problems
    shared = env.tmp / "shared"
    shared.mkdir()
    in_shared = _script(env, "print(1)", parent=shared)
    shared.chmod(0o777)
    problems = lp.validate_command([sys.executable, str(in_shared), "{output}"], "tts")[0]
    assert any(p.startswith("argv[1]") and "writable" in p for p in problems), problems
    shared.chmod(0o755)
    big = env.tmp / "scripts" / "big.py"
    with open(big, "wb") as fh:
        fh.truncate(64 * 1024 * 1024 + 1)
    big.chmod(0o644)
    problems = lp.validate_command([sys.executable, str(big), "{output}"], "tts")[0]
    assert any(p.startswith("argv[1]") and "64 MiB" in p for p in problems), problems
    for script in ("-c", "relative.py"):
        assert lp.validate_command([sys.executable, script, "{output}"], "tts")[0]


def test_f0_the_card_names_every_bound_file(armed, client, orch):
    env = armed
    script = _script(env, "print(1)")
    argv = [sys.executable, str(script), "{output}"]
    resp = client.post("/api/admin/voice/commands", headers=ADMIN, json={"side": "tts", "argv": argv})
    assert resp.status_code == 202, resp.text
    [task] = _pending(orch)
    files = task.payload["preview"]["files"]
    assert [f["path"] for f in files] == [str(Path(sys.executable).resolve()), str(script.resolve())]
    assert files[1]["size"] == script.stat().st_size and len(files[1]["sha256"]) == 64
    assert str(script.resolve()) in task.title or str(Path(sys.executable).resolve()) in task.title


def test_f1_an_ancestor_writable_by_others_without_the_sticky_bit_is_refused(env):
    anc = env.tmp / "anc"
    exe = _fake(anc / "bin" / "say", env.tmp)
    argv = [str(exe), "{output}"]
    assert lp.validate_command(argv, "tts")[0] == []
    for mode, refused in ((0o777, True), (0o775, True), (0o1777, False), (0o755, False)):
        anc.chmod(mode)
        problems = lp.validate_command(argv, "tts")[0]
        assert bool(problems) is refused, (oct(mode), problems)
    (anc / "bin").chmod(0o775)
    assert lp.validate_command(argv, "tts")[0]
    (anc / "bin").chmod(0o755)


@pytest.mark.asyncio
async def test_f1_a_program_swapped_while_waiting_for_a_slot_never_runs(armed, monkeypatch):
    env = armed
    anc = env.tmp / "anc"
    exe = _fake(anc / "bin" / "say", env.tmp)
    await _approve(env, "tts", [str(exe), "--out", "{output}"])
    gate = asyncio.Semaphore(0)
    monkeypatch.setattr(lp, "_slot", lambda: gate)
    task = asyncio.create_task(lp.speak_command("hi", "en", temp_dir=env.temp))
    for _ in range(100):                                   # past the first check, waiting for a slot
        if _run_dirs(env):
            break
        await asyncio.sleep(0.05)
    assert _run_dirs(env) and not task.done()
    marker = env.tmp / "evil-ran"
    os.rename(anc / "bin", anc / "bin_old")
    (anc / "bin").mkdir()
    swapped = anc / "bin" / "say"
    swapped.write_text(f"#!{sys.executable}\nopen({str(marker)!r}, 'w').write('EVIL')\n")
    swapped.chmod(0o755)
    gate.release()
    assert await task is None
    assert not marker.exists() and _records(env.tmp) == []


@pytest.mark.asyncio
async def test_f2_a_timeout_kills_the_whole_process_group(armed, monkeypatch):
    env = armed
    pidfile = env.tmp / "grandchild.pid"
    wrapper = env.tmp / "opt" / "stt-wrapper"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(f"#!/bin/sh\n/bin/sleep 300 &\necho $! > {pidfile}\nwait\n")
    wrapper.chmod(0o755)
    await _approve(env, "stt", [str(wrapper), "{audio}"])
    monkeypatch.setattr(lp, "STT_TIMEOUT_S", 1)
    start = time.monotonic()
    pid = None
    try:
        assert await lp.transcribe_command(OGG, "en", temp_dir=env.temp) == "[STT error: command timed out]"
        elapsed = time.monotonic() - start
        pid = int(pidfile.read_text().strip())
        for _ in range(40):
            if not _alive(pid):
                break
            await asyncio.sleep(0.05)
        assert not _alive(pid)
        assert elapsed < 5
    finally:
        if pid is None and pidfile.exists():
            pid = int(pidfile.read_text().strip())
        if pid is not None and _alive(pid):
            os.kill(pid, 9)


def _named(env, name: str) -> Path:
    return _fake(env.tmp / "named" / name, env.tmp)


def test_f3_programs_that_run_other_programs_are_refused(env):
    demonstrated = [
        ["/lib64/ld-linux-x86-64.so.2", "/bin/sh", "-s", "{output}"],
        ["/usr/bin/find", "/", "-maxdepth", "0", "-exec", "/bin/sh", "-c", "id", ";", "{output}"],
        ["/usr/bin/awk", 'system("id")', "{output}"],
        ["/usr/bin/git", "-c", "core.pager=sh", "{output}"],
    ]
    for argv in demonstrated:
        if not os.path.exists(argv[0]):
            continue
        problems = lp.validate_command(argv, "tts")[0]
        assert any("launcher" in p for p in problems), (argv[0], problems)
    for name in ("ld.so", "ld-linux-aarch64.so.1", "ld-musl-x86_64.so.1", "find", "xargs", "gawk", "mawk", "nawk",
                 "sed", "env", "nohup", "timeout", "nice", "ionice", "setsid", "stdbuf", "script", "expect",
                 "tclsh8.6", "wish", "R", "Rscript", "osascript", "cmd.exe", "pwsh", "wine", "docker", "podman",
                 "ssh", "su", "doas", "pkexec", "systemd-run", "flatpak", "busybox", "toybox", "make", "git", "vim",
                 "vi", "nvim", "emacs", "less", "more", "man", "gdb", "strace", "ltrace"):
        exe = _named(env, name)
        problems = lp.validate_command([str(exe), "{output}"], "tts")[0]
        assert any("launcher" in p for p in problems), (name, problems)
    script = _script(env, "puts 1", name="say.rb")
    for name in ("ruby", "php", "lua5.4"):
        exe = _named(env, name)
        assert lp.validate_command([str(exe), str(script), "{output}"], "tts")[0] == [], name
        assert lp.validate_command([str(exe), "-e", "x", "{output}"], "tts")[0], name
    prog = _named(env, "my-tts")
    assert any("shell" in p for p in lp.validate_command([str(prog), "/bin/sh", "{output}"], "tts")[0])


@pytest.mark.asyncio
@pytest.mark.parametrize("voice,local_only,has_edge", [(None, True, True), ("piper:en_US-xtts-clone", True, True),
                                                      (None, False, False)])
async def test_f5_the_auto_pick_never_speaks_a_flagged_model_without_consent(env, monkeypatch, voice, local_only,
                                                                             has_edge):
    _piper(env, "en_US-xtts-clone")
    settings_db.put_category("voice", {"local_only": local_only})
    monkeypatch.setattr(tts_module, "HAS_EDGE", has_edge)
    monkeypatch.setattr(tts_module, "HAS_KOKORO", False)
    blocked = _engine(consent_getter=lambda: False)
    monkeypatch.setattr(blocked, "_speak_edge", _edge_stub)
    await blocked.speak("hello", voice=voice, lang="en")
    assert _records(env.tmp) == []
    allowed = _engine(consent_getter=lambda: True)
    monkeypatch.setattr(allowed, "_speak_edge", _edge_stub)
    if not has_edge or local_only:
        path = await allowed.speak("hello", voice=voice, lang="en")
        assert path and path.endswith(".wav") and len(_records(env.tmp)) == 1


@pytest.mark.asyncio
async def test_f6_apply_writes_only_what_the_card_showed(armed, orch):
    env = armed
    good = _fake(env.tmp / "opt" / "good-tts", env.tmp)
    other = _fake(env.tmp / "opt" / "other-tts", env.tmp)
    status, _ = await command_settings.request(orch, "tts", [str(good), "{output}"])
    assert status == 202
    [task] = _pending(orch)
    argv = [str(other), "{output}"]
    _, exe = lp.validate_command(argv, "tts")
    edited = dict(task.payload)
    edited.update(argv=argv, fingerprint=command_settings._fingerprint(argv), exe_identity=lp.exe_identity(exe),
                  bound=[lp.exe_identity(exe)])
    await orch.autonomy.apply_decision(task.id, "edit", decided_by="admin", payload=edited)
    accepted = await orch.autonomy.apply_decision(task.id, "accept", decided_by="owner")
    assert accepted.decision == "accept"
    result = await irreversible.execute(accepted, orch=orch)
    assert result["status"] == "refused" and result["reason"] == "payload_changed", result
    assert lp.stored_command("tts") == {}
    # a task nobody requested through the route (POST /autonomy/tasks) has no record
    direct = SimpleNamespace(id=4242, kind=command_settings.APPROVAL_KIND, decided_by="owner", decision="accept",
                             payload=dict(edited))
    assert (await irreversible.execute(direct, orch=orch))["reason"] == "not_requested"
    # only a plain accept applies: an edit decision is refused even on the card's own payload
    status, _ = await command_settings.request(orch, "stt", _stt_argv(good))
    [stt_task] = [t for t in _pending(orch) if t.payload["side"] == "stt"]
    for decision in ("edit", "reject", "defer"):
        again = SimpleNamespace(id=stt_task.id, kind=stt_task.kind, decided_by="owner", decision=decision,
                                payload=stt_task.payload)
        assert (await command_settings.apply_approved(again, orch))["status"] == "refused", decision
    plain = SimpleNamespace(id=stt_task.id, kind=stt_task.kind, decided_by="owner", decision="accept",
                            payload=stt_task.payload)
    assert (await irreversible.execute(plain, orch=orch))["status"] == "ok"
    assert lp.stored_command("stt")["argv"] == _stt_argv(good)


@pytest.mark.asyncio
async def test_f7_local_only_never_runs_the_tts_command(armed, client, monkeypatch):
    from agents.core.channels.spoken_reply import SpokenReply

    env = armed
    exe = _fake(env.tmp / "opt" / "say-wav", env.tmp)
    await _approve(env, "tts", _tts_argv(exe))
    monkeypatch.setattr(tts_module, "HAS_EDGE", False)
    monkeypatch.setattr(tts_module, "HAS_KOKORO", False)
    assert SpokenReply().backend_label() == "your TTS command (locality not checked)"
    caps = client.get("/api/voice/capabilities").json()
    assert caps["tts_local"] is False
    _piper(env, "en_US-amy-low")
    settings_db.put_category("voice", {"local_only": True})
    path = await _engine().speak("hello", voice="command", lang="en")
    assert path and path.endswith(".wav")
    assert [r["argv"][0] for r in _records(env.tmp)] == [str((env.bin / "piper").resolve())]
    label = next(row["label"] for row in settings_db.DEFAULTS if row["key"] == "local_only")
    assert "command" in label.lower() and "xtts" in label.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("lang", [None, "", "fr", "en"])
async def test_f8_a_failing_local_default_voice_falls_back_to_an_edge_voice(env, monkeypatch, lang):
    _piper(env)                                               # the binary, no model: Piper fails
    monkeypatch.setattr(tts_module, "HAS_EDGE", True)
    for default in ("piper:ro_RO-mihai-medium", "command"):
        engine = _engine(default_voice=default)
        edge = []

        async def fake_edge(text, voice, seen=edge):
            seen.append(voice)
            return "edge"

        monkeypatch.setattr(engine, "_speak_edge", fake_edge)
        assert await engine.speak("Salut", lang=lang) == "edge", default
        assert edge and edge[0] in TTSEngine.VOICE_MAP.values(), (default, edge)
        assert tts_module.local_voice_kind(engine._safe_default_voice(lang)) is None


def test_f9_the_hud_tts_keeps_the_owners_piper_voice_when_a_lang_is_sent(env, client, monkeypatch):
    import core.voice.local_providers as core_lp
    import core.voice.tts as core_tts

    _piper(env, "ro_RO-mihai-medium", "en_US-amy-low")
    monkeypatch.setattr(core_tts, "HAS_EDGE", True)
    monkeypatch.setattr(core_tts, "TEMP_DIR", env.temp)
    monkeypatch.setattr(core_lp, "_import_piper", lambda: None)
    edge = []

    async def fake_edge(self, text, voice):
        edge.append(voice)
        return None

    monkeypatch.setattr(core_tts.TTSEngine, "_speak_edge", fake_edge)
    monkeypatch.setattr("core.settings_db.get_value", settings_db.get_value)   # the route's copy: this DB
    settings_db.put_category("voice", {"tts_voice": "piper:en_US-amy-low"})
    resp = client.post("/tts", json={"text": "Salut lume", "lang": "ro"})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "audio/wav" and edge == []
    assert _records(env.tmp)[-1]["argv"][2].endswith("en_US-amy-low.onnx")
    settings_db.put_category("voice", {"tts_voice": "piper"})              # bare: the model for the language
    resp = client.post("/tts", json={"text": "Salut lume", "lang": "ro"})
    assert resp.status_code == 200 and edge == []
    assert _records(env.tmp)[-1]["argv"][2].endswith("ro_RO-mihai-medium.onnx")


@pytest.mark.asyncio
async def test_f9_a_spoken_reply_with_a_lang_keeps_the_owners_piper_voice(env, monkeypatch):
    from agents.core.channels.spoken_reply import SpokenReply

    _piper(env, "en_US-amy-low")
    monkeypatch.setattr(tts_module, "HAS_EDGE", True)
    edge = []

    async def fake_edge(self, text, voice):
        edge.append(voice)
        return None

    monkeypatch.setattr(tts_module.TTSEngine, "_speak_edge", fake_edge)
    settings_db.put_category("voice", {"tts_voice": "piper:en_US-amy-low"})
    audio = await SpokenReply()("Salut lume, ce faci?", lang="ro")
    assert audio.ok and audio.mime == "audio/wav" and edge == []
    assert _records(env.tmp)[-1]["argv"][2].endswith("en_US-amy-low.onnx")


class _FakePiperVoice:
    @classmethod
    def load(cls, model, config_path=None):
        return cls()

    def synthesize_wav(self, text, wav_file):
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\0\0" * 10)


@pytest.mark.asyncio
async def test_f10_a_synthesis_cancelled_while_queued_releases_the_piper_slot(env, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    _piper(env, "en_US-amy-low")
    monkeypatch.setattr(lp, "_import_piper", lambda: _FakePiperVoice)
    monkeypatch.setattr(lp, "TTS_TIMEOUT_S", 0.3)
    loop = asyncio.get_running_loop()
    pool = ThreadPoolExecutor(max_workers=1)
    loop.set_default_executor(pool)
    release = threading.Event()
    real_workdir = lp.private_workdir
    blocked = []

    @__import__("contextlib").asynccontextmanager
    async def busy_pool_workdir(temp_dir):
        if not blocked:                           # the pool is busy when the synthesis is queued
            blocked.append(loop.run_in_executor(None, release.wait, 10))
        async with real_workdir(temp_dir) as workdir:
            yield workdir

    monkeypatch.setattr(lp, "private_workdir", busy_pool_workdir)
    try:
        assert await lp.speak_piper("hi", "piper:en_US-amy-low", "en", temp_dir=env.temp) is None
        release.set()
        await blocked[0]
        path = await lp.speak_piper("hi", "piper:en_US-amy-low", "en", temp_dir=env.temp)
        assert path and path.endswith(".wav")
        assert lp._PKG_SLOT.acquire(blocking=False)
        lp._PKG_SLOT.release()
    finally:
        release.set()
        pool.shutdown(wait=False)


@pytest.mark.asyncio
async def test_f11_whisper_timestamps_are_stripped_and_other_brackets_are_text(armed, monkeypatch):
    from agents.core.channels.inbound_voice import InboundVoiceReader

    env = armed
    out = env.tmp / "stdout.txt"
    exe = env.tmp / "opt" / "whisper-cli"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text(f"#!{sys.executable}\nimport sys\nsys.stdout.write(open({str(out)!r}).read())\n")
    exe.chmod(0o755)
    await _approve(env, "stt", [str(exe), "-f", "{audio}"])
    out.write_text("[00:00:00.000 --> 00:00:02.500]   Salut, ce faci?\n[00:00:02.500 --> 00:00:03.000]  Bine.\n")
    assert await lp.transcribe_command(OGG, "ro", temp_dir=env.temp) == "Salut, ce faci? Bine."
    out.write_text("[laughs] hello there\n")
    text = await lp.transcribe_command(OGG, "en", temp_dir=env.temp)
    assert text == "[laughs] hello there"
    for sentinel, ok in (("[laughs] hello there", True), ("[silence]", False), ("[STT unavailable]", False),
                         ("[STT error: command exited 3]", False), ("[music]", True)):
        assert lp.is_stt_sentinel(sentinel) is (not ok), sentinel

        async def transcribe(audio, language, value=sentinel):
            return value

        heard = await InboundVoiceReader(transcribe=transcribe, available=True)(OGG, language="en")
        assert heard.ok is ok, sentinel
    out.write_text("[BLANK_AUDIO]\n")
    assert await lp.transcribe_command(OGG, "en", temp_dir=env.temp) == "[silence]"


def test_f12_tts_availability_honours_local_only(env, client, monkeypatch):
    import core.voice.tts as core_tts

    from agents.core.channels.spoken_reply import SpokenReply
    from agents.core.routers import voice as voice_router
    from agents.core.voice import speak_tool

    for module in (core_tts, tts_module):
        monkeypatch.setattr(module, "HAS_EDGE", True)
        monkeypatch.setattr(module, "HAS_KOKORO", False)
    monkeypatch.setattr(voice_router, "_caps_cache",
                        {"has_whisper": False, "has_edge": True, "has_kokoro": False, "consent_fn": None})
    settings_db.put_category("voice", {"local_only": True})
    assert tts_module.tts_available() is False
    resp = client.post("/tts", json={"text": "hello", "lang": "en"})
    assert resp.status_code == 503, resp.text
    assert client.get("/api/voice/capabilities").json()["tts"] is False
    assert speak_tool.tts_installed() is False and SpokenReply().is_available is False
    settings_db.put_category("voice", {"local_only": False})
    assert tts_module.tts_available() is True and speak_tool.tts_installed() is True


def test_f18_stt_availability_honours_stt_engine(armed, client, monkeypatch):
    import core.voice.stt as core_stt

    from agents.core.channels.inbound_voice import InboundVoiceReader
    from agents.core.routers import voice as voice_router

    env = armed
    exe = _fake(env.tmp / "opt" / "stt", env.tmp, no_stdin=True)
    asyncio.run(_approve(env, "stt", _stt_argv(exe)))
    for module in (core_stt, stt_module):
        monkeypatch.setattr(module, "HAS_WHISPER", False)
    caps = {"has_whisper": False, "has_edge": False, "has_kokoro": False, "consent_fn": None}
    monkeypatch.setattr(voice_router, "_caps_cache", caps)
    settings_db.put_category("voice", {"stt_engine": "whisper"})
    resp = client.post("/api/voice/stt?lang=en", content=OGG, headers={"content-type": "audio/ogg"})
    assert resp.status_code == 503, resp.text
    assert client.get("/api/voice/capabilities").json()["stt"] is False
    assert InboundVoiceReader().is_available is False
    settings_db.put_category("voice", {"stt_engine": "command"})
    assert InboundVoiceReader().is_available is True
    asyncio.run(command_settings.clear(None, "stt"))
    for module in (core_stt, stt_module):
        monkeypatch.setattr(module, "HAS_WHISPER", True)
    monkeypatch.setitem(caps, "has_whisper", True)
    resp = client.post("/api/voice/stt?lang=en", content=OGG, headers={"content-type": "audio/ogg"})
    assert resp.status_code == 503, resp.text
    assert client.get("/api/voice/capabilities").json()["stt"] is False
    assert InboundVoiceReader().is_available is False


@pytest.mark.asyncio
async def test_f13_piper_is_imported_off_the_event_loop_and_probes_never_import_it(env, monkeypatch):
    import threading

    from agents.core.channels.spoken_reply import SpokenReply
    from agents.core.voice import speak_tool

    _piper(env, "en_US-amy-low")
    loop_thread = threading.get_ident()
    seen = []

    def fake_import():
        seen.append(threading.get_ident())
        return _FakePiperVoice

    monkeypatch.setattr(lp, "_import_piper", fake_import)
    path = await lp.speak_piper("hi", "piper:en_US-amy-low", "en", temp_dir=env.temp)
    assert path and seen and loop_thread not in seen
    seen.clear()
    monkeypatch.setattr(tts_module, "HAS_EDGE", False)
    monkeypatch.setattr(tts_module, "HAS_KOKORO", False)
    assert speak_tool.tts_installed() is True and SpokenReply().is_available is True
    assert seen == []


def test_f14_a_piper_voice_speaks_the_language_of_its_model_name(env):
    from agents.core.voice.speech_text import speech_lang

    engine = TTSEngine(default_voice="piper:ro_RO-mihai-medium")
    assert engine.speech_for("Salut lume, 50% & gata", lang="") == "Salut lume, 50 la sută și gata"
    assert speech_lang("", "piper:ro_RO-mihai-medium") == "ro"
    assert speech_lang("", "piper:en_US-amy-low", default="ro") == "en"


@pytest.mark.asyncio
async def test_f14_the_bare_piper_pick_uses_the_default_models_language(env, monkeypatch):
    _piper(env, "en_US-amy-low", "ro_RO-mihai-medium")
    settings_db.put_category("voice", {"local_only": True})
    monkeypatch.setattr(tts_module, "HAS_KOKORO", False)
    engine = _engine(default_voice="piper:ro_RO-missing-model")
    path = await engine.speak("Salut", lang=None)
    assert path and path.endswith(".wav")
    assert _records(env.tmp)[-1]["argv"][2].endswith("ro_RO-mihai-medium.onnx")


@pytest.mark.asyncio
async def test_f15_a_flac_clip_is_sent_as_flac(tmp_path):
    from agents.core.channels import telegram
    from agents.core.channels.spoken_reply import SpokenReply
    from agents.core.voice import speak_tool

    clip = tmp_path / "reply.flac"
    clip.write_bytes(b"fLaC" + b"\0" * 60)

    async def synth(text, lang):
        return str(clip)

    audio = await SpokenReply(synthesize=synth, available=True, backend="command")("Hello there, friend.", lang="en")
    assert audio.ok and audio.mime == "audio/flac"
    assert speak_tool._AUDIO_SUFFIX["audio/flac"] == ".flac"
    assert telegram.VOICE_SUFFIX["audio/flac"] == "flac"


def test_f17_a_clear_needs_an_explicit_clear_and_a_dry_run_never_writes(armed, client, orch):
    env = armed
    exe = _fake(env.tmp / "opt" / "say-wav", env.tmp)
    asyncio.run(_approve(env, "tts", _tts_argv(exe)))
    stored = lp.stored_command("tts")
    for body in ({"side": "tts"}, {"side": "tts", "dry_run": True}, {"side": "tts", "args": _tts_argv(exe)},
                 {"side": "tts", "argv": None}, {"side": "tts", "argv": []},
                 {"side": "tts", "clear": True, "argv": _tts_argv(exe)}):
        resp = client.post("/api/admin/voice/commands", headers=ADMIN, json=body)
        assert resp.status_code == 422, (body, resp.status_code, resp.text)
        assert lp.stored_command("tts") == stored
    resp = client.post("/api/admin/voice/commands", headers=ADMIN, json={"side": "tts", "clear": True, "dry_run": True})
    assert resp.status_code == 200 and resp.json()["dry_run"] is True
    assert lp.stored_command("tts") == stored
    resp = client.post("/api/admin/voice/commands", headers=ADMIN, json={"side": "tts", "clear": True})
    assert resp.status_code == 200 and resp.json()["cleared"] is True and lp.stored_command("tts") == {}


def test_f19_the_settings_label_and_docs_name_where_the_block_lives():
    root = Path(__file__).resolve().parents[1]
    where = "Console → Admin → Settings → Voice → Command providers"
    texts = [settings_db.ROUTE_ONLY[("voice", "tts_command")], settings_db.ROUTE_ONLY[("voice", "stt_command")]]
    texts += [row["label"] for row in settings_db.DEFAULTS if row["key"] in ("tts_command", "stt_command")]
    texts += [(root / "docs" / "FLAGS.md").read_text(encoding="utf-8"), (root / ".env.example").read_text(encoding="utf-8")]
    for text in texts:
        text = text.replace("->", "→")
        assert where in text and "Console → Voice →" not in text


def test_f20_the_tts_503_hint_names_the_piper_model():
    from agents.core.routers import voice as voice_router

    assert "piper-tts" in voice_router.NO_TTS and ".onnx.json" in voice_router.NO_TTS
    assert "<data>/voice/piper" in voice_router.NO_TTS and "voice.piper_model_dir" in voice_router.NO_TTS


# ── verify round (N1–N3) ──────────────────────────────────────────────────────────────

PY_SIBLING = ("import site, sys\n"
              "try:\n    import n1_sidekick\nexcept ImportError:\n    pass\n"
              "open(sys.argv[1], 'wb').write({wav!r})\n"
              "open({marker!r}, 'a').write('user_site=%s\\n' % site.ENABLE_USER_SITE)\n")


@pytest.mark.asyncio
async def test_n1_a_python_script_never_imports_from_its_own_folder_or_user_site(armed):
    env = armed
    marker = env.tmp / "marker"
    script = _script(env, PY_SIBLING.format(wav=WAV, marker=str(marker)))
    assert (await _approve(env, "tts", [sys.executable, str(script), "{output}"]))["status"] == "ok"
    (script.parent / "n1_sidekick.py").write_text(
        f"open({str(marker)!r}, 'a').write('UNAPPROVED\\n')\n", encoding="utf-8")
    assert lp.command_ready("tts").ok                         # no bound file changed
    assert await lp.speak_command("hi", "en", temp_dir=env.temp)
    text = marker.read_text()
    assert "UNAPPROVED" not in text and "user_site=False" in text, text


def test_n1_the_card_note_says_what_approving_does_not_bind():
    note = command_settings.NOTE
    assert "not bound" in note and "Python" in note


def test_n2_a_waiting_card_for_a_program_that_changed_is_not_handed_back(armed, client, orch):
    env = armed
    exe = _fake(env.tmp / "opt" / "say-wav", env.tmp)
    argv = _tts_argv(exe)
    first = client.post("/api/admin/voice/commands", headers=ADMIN, json={"side": "tts", "argv": argv})
    assert first.status_code == 202, first.text
    exe.write_bytes(exe.read_bytes() + b"\n# upgraded\n")
    again = client.post("/api/admin/voice/commands", headers=ADMIN, json={"side": "tts", "argv": argv})
    assert again.status_code == 409, again.text
    body = again.json()
    assert body["error"] == "request_stale" and body["pending"] == first.json()["pending"]
    assert "changed" in body["detail"] and len(_pending(orch)) == 1


@pytest.mark.asyncio
async def test_n3_local_only_tries_a_failing_piper_voice_once(env, monkeypatch):
    _piper(env, "ro_RO-x-medium")
    _mode(env.tmp, "fail")
    monkeypatch.setattr(tts_module, "HAS_KOKORO", False)
    settings_db.put_category("voice", {"local_only": True})
    assert await _engine().speak("Salut", voice="piper:ro_RO-x-medium", lang="ro") is None
    assert len(_records(env.tmp)) == 1


@pytest.mark.asyncio
async def test_n3_local_only_still_tries_another_piper_model_after_a_missing_one(env, monkeypatch):
    _piper(env, "ro_RO-y-medium")
    monkeypatch.setattr(tts_module, "HAS_KOKORO", False)
    settings_db.put_category("voice", {"local_only": True})
    path = await _engine().speak("Salut", voice="piper:ro_RO-missing-low", lang="ro")
    assert path and path.endswith(".wav")
    [rec] = _records(env.tmp)
    assert any("ro_RO-y-medium" in arg for arg in rec["argv"])
