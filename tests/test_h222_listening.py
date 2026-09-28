"""H222 — whether Nerva is listening, for an indicator outside the main window.

The voice paths publish their state (the host's wake-word detector and capture, and
Wyoming satellites that say they are capturing); anything reads or follows it through
one in-process registry and two read-only routes; the HUD forwards it to the desktop
shell, whose tray shows the loudest window's state.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.core.voice import listening
from agents.core.voice.wyoming import LISTEN_EVENTS, WyomingEvent, WyomingServer, encode_event

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean_state():
    listening.STATE.reset()
    yield
    listening.STATE.reset()


# ── the registry ─────────────────────────────────────────────────────────────


def test_off_by_default():
    snap = listening.snapshot()
    assert snap["state"] == "off" and snap["mic_open"] is False and snap["sources"] == {}


def test_the_loudest_source_wins_and_an_open_mic_outranks_the_rest():
    s = listening.ListeningState()
    s.set_state("hub", "speaking")
    assert s.snapshot()["state"] == "speaking" and s.snapshot()["mic_open"] is False
    s.set_state("satellite:kitchen", "thinking")
    assert s.snapshot()["state"] == "thinking"
    s.set_state("hub", "armed")
    snap = s.snapshot()
    assert snap["state"] == "armed" and snap["mic_open"] is True
    s.set_state("satellite:kitchen", "listening")
    snap = s.snapshot()
    assert snap["state"] == "listening" and snap["mic_open"] is True
    assert snap["sources"] == {"hub": "armed", "satellite:kitchen": "listening"}
    s.set_state("satellite:kitchen", "off")
    assert s.snapshot()["sources"] == {"hub": "armed"}, "off forgets the source"
    assert list(listening.ORDER) == ["listening", "armed", "thinking", "speaking", "off"]


@pytest.mark.parametrize("source, state", [
    ("", "listening"), ("hub", "on"), ("hub", "LISTENING"), ("two words", "armed"),
    ("tab\there", "armed"), ("x" * (listening.MAX_SOURCE_LEN + 1), "armed"), (None, "armed"),
    ("bell\x07", "armed"),
])
def test_a_bad_source_or_state_is_refused(source, state):
    s = listening.ListeningState()
    assert s.set_state(source, state) is False
    assert s.snapshot()["sources"] == {} and s.snapshot()["seq"] == 0


def test_the_sequence_moves_only_on_a_change_and_subscribers_hear_only_changes():
    s = listening.ListeningState()
    heard = []
    s.subscribe(heard.append)
    assert s.set_state("hub", "armed") is True
    assert s.snapshot()["seq"] == 1
    assert s.set_state("hub", "armed") is True
    assert s.snapshot()["seq"] == 1 and len(heard) == 1
    s.set_state("hub", "listening")
    assert s.snapshot()["seq"] == 2 and [h["state"] for h in heard] == ["armed", "listening"]
    s.set_state("nobody", "off")                                  # off for an unknown source
    assert s.snapshot()["seq"] == 2 and len(heard) == 2
    s.unsubscribe(heard.append)
    s.unsubscribe(heard.append)                                   # twice is harmless
    s.set_state("hub", "off")
    assert len(heard) == 2 and s.snapshot()["seq"] == 3


def test_unsubscribing_one_follower_keeps_the_others():
    s = listening.ListeningState()
    tray, log = [], []
    s.subscribe(tray.append)
    s.subscribe(log.append)
    s.unsubscribe(log.append)
    s.set_state("hub", "armed")
    assert len(tray) == 1 and log == []


def test_a_failing_subscriber_never_breaks_the_voice_path():
    s = listening.ListeningState()
    good = []

    def boom(snap):
        raise RuntimeError("x")

    s.subscribe(boom)
    s.subscribe(good.append)
    assert s.set_state("hub", "listening") is True
    assert len(good) == 1


def test_a_stuck_transient_state_expires_but_an_armed_mic_stays():
    now = [100.0]
    s = listening.ListeningState(clock=lambda: now[0])
    s.set_state("hub", "armed")
    s.set_state("satellite:a", "listening")
    now[0] += listening.STALE_SECONDS - 1
    assert s.snapshot()["sources"] == {"hub": "armed", "satellite:a": "listening"}
    seq = s.snapshot()["seq"]
    now[0] += 2
    snap = s.snapshot()
    assert snap["sources"] == {"hub": "armed"} and snap["state"] == "armed"
    assert snap["seq"] == seq + 1, "an expiry is a change a poller must see"
    for transient in ("thinking", "speaking"):
        s.set_state("hub", transient)
        now[0] += listening.STALE_SECONDS + 1
        assert s.snapshot()["sources"] == {}
    s.set_state("hub", "listening")
    now[0] += listening.STALE_SECONDS - 1
    seq = s.snapshot()["seq"]
    s.set_state("hub", "listening")                               # re-said: a heartbeat, not a change
    assert s.snapshot()["seq"] == seq
    now[0] += 2
    assert s.snapshot()["sources"] == {"hub": "listening"}


def test_a_refreshed_transient_state_does_not_expire():
    now = [0.0]
    s = listening.ListeningState(clock=lambda: now[0])
    s.set_state("hub", "listening")
    now[0] += listening.STALE_SECONDS - 1
    s.set_state("hub", "thinking")
    now[0] += listening.STALE_SECONDS - 1
    assert s.snapshot()["sources"] == {"hub": "thinking"}


def test_sources_are_bounded():
    s = listening.ListeningState()
    for i in range(listening.MAX_SOURCES):
        assert s.set_state(f"satellite:{i}", "armed") is True
    assert s.set_state("satellite:extra", "armed") is False
    assert s.set_state("satellite:0", "listening") is True, "a known source still moves"
    s.set_state("satellite:1", "off")
    assert s.set_state("satellite:extra", "armed") is True


def test_satellite_source_names():
    assert listening.satellite_source("kitchen") == "satellite:kitchen"
    assert listening.satellite_source("  ") == "satellite"
    assert listening.satellite_source(None) == "satellite"


def test_the_module_functions_use_the_one_process_state():
    heard = []
    listening.subscribe(heard.append)
    assert listening.set_state("hub", "armed") is True
    assert listening.snapshot()["state"] == "armed" and len(heard) == 1
    listening.unsubscribe(heard.append)
    listening.set_state("hub", "off")
    assert len(heard) == 1


def test_every_voice_path_and_route_shares_one_registry():
    """`core.X` and `agents.core.X` are different modules here; the hub loads the
    `agents.core` copy, and so must every writer and reader of this state."""
    from agents import web  # noqa: F401 — load the app as the hub does
    from agents.core.routers import voice as voice_routes
    from agents.core.voice import pipeline, wake_word, wyoming

    assert pipeline.listening is listening and wake_word.listening is listening
    assert wyoming.listening is listening
    assert "core.voice.listening" not in sys.modules
    src = (ROOT / "agents" / "core" / "routers" / "voice.py").read_text(encoding="utf-8")
    assert "from agents.core.voice import listening" in src and "core.voice.listening" not in src.replace(
        "agents.core.voice", "")
    assert voice_routes.voice_listening is not None


# ── the host's own voice path ────────────────────────────────────────────────


def test_the_wake_word_detector_marks_the_mic_open_while_it_runs(monkeypatch):
    from agents.core.voice import wake_word

    class _Audio:
        def open(self, **kw):
            return SimpleNamespace(stop_stream=lambda: None, close=lambda: None)

        def terminate(self):
            pass

    monkeypatch.setattr(wake_word, "HAS_OWW", True)
    monkeypatch.setattr(wake_word, "HAS_PYAUDIO", True)
    monkeypatch.setattr(wake_word, "openwakeword", SimpleNamespace(OWWModel=lambda: object()), raising=False)
    monkeypatch.setattr(wake_word, "pyaudio", SimpleNamespace(PyAudio=_Audio, paInt16=8), raising=False)
    seen = []

    async def loop(self):
        seen.append(listening.snapshot()["sources"])

    monkeypatch.setattr(wake_word.WakeWordDetector, "_listen_loop", loop)
    det = wake_word.WakeWordDetector()
    assert det.running is False
    asyncio.run(det.start())
    assert seen == [{"hub": "armed"}] and det.running is True
    det.stop()
    assert det.running is False and listening.snapshot()["sources"] == {}


def test_a_detector_without_its_libraries_never_claims_the_mic(monkeypatch):
    from agents.core.voice import wake_word

    monkeypatch.setattr(wake_word, "HAS_OWW", False)
    asyncio.run(wake_word.WakeWordDetector().start())
    assert listening.snapshot()["sources"] == {}


def _pipeline(*, detector_running=True, audio="in.wav", text="hello", reply="hi there", spoken="out.mp3",
              fail=None):
    from agents.core.voice.pipeline import VoicePipeline

    trail = []

    def mark(step):
        trail.append((step, listening.snapshot()["sources"].get("hub", "off")))

    p = VoicePipeline.__new__(VoicePipeline)
    p.detector = SimpleNamespace(running=detector_running, stop=lambda: None)

    async def record():
        mark("record")
        return audio

    async def transcribe(path):
        mark("stt")
        if fail:
            raise fail
        return text

    async def answer(t):
        mark("answer")
        return reply

    async def speak(r):
        mark("tts")
        return spoken

    async def play(path):
        mark("play")

    p._record_audio = record
    p.stt = SimpleNamespace(transcribe_async=transcribe)
    p.tts = SimpleNamespace(speak=speak)
    p.on_transcription = answer
    p._play_audio = play
    return p, trail


def test_a_capture_says_listening_then_thinking_then_speaking_then_goes_back_to_the_wake_word():
    p, trail = _pipeline()
    asyncio.run(p._capture_and_process("jarvis"))
    assert trail == [("record", "listening"), ("stt", "thinking"), ("answer", "thinking"),
                     ("tts", "thinking"), ("play", "speaking")]
    assert listening.snapshot()["sources"] == {"hub": "armed"}


def test_without_the_detector_a_finished_capture_is_off():
    p, _ = _pipeline(detector_running=False)
    asyncio.run(p._capture_and_process("jarvis"))
    assert listening.snapshot()["sources"] == {}


@pytest.mark.parametrize("kw", [{"audio": None}, {"text": "[silence]"}, {"text": ""}, {"reply": ""},
                                {"spoken": None}])
def test_every_early_end_goes_back_to_the_wake_word(kw):
    p, trail = _pipeline(**kw)
    asyncio.run(p._capture_and_process("jarvis"))
    assert listening.snapshot()["sources"] == {"hub": "armed"}
    assert ("play", "speaking") not in trail


def test_a_failing_capture_never_leaves_the_indicator_on():
    p, _ = _pipeline(fail=RuntimeError("whisper"))
    with pytest.raises(RuntimeError):
        asyncio.run(p._capture_and_process("jarvis"))
    assert listening.snapshot()["sources"] == {"hub": "armed"}


def test_stopping_the_pipeline_closes_the_indicator():
    from agents.core.voice.pipeline import VoicePipeline

    p = VoicePipeline.__new__(VoicePipeline)
    p.detector = SimpleNamespace(stop=lambda: None, running=False)
    listening.set_state("hub", "listening")
    p.stop()
    assert listening.snapshot()["sources"] == {}


# ── Wyoming satellites ───────────────────────────────────────────────────────


class _Writer:
    def __init__(self):
        self.buf = bytearray()

    def write(self, data):
        self.buf.extend(data)

    async def drain(self):
        pass

    def close(self):
        pass

    def get_extra_info(self, name, default=None):
        return ("127.0.0.1", 5555)


def _auth_server(seen):
    hub = SimpleNamespace(
        authenticate=lambda **kw: {"ok": True, "principal": SimpleNamespace(satellite_id="kitchen")},
        validate_principal=lambda principal: {"ok": True},
    )
    resolver = SimpleNamespace(resolve=lambda principal: SimpleNamespace(room="kitchen"))

    async def room_handler(text, context):
        seen.append(listening.snapshot()["sources"])
        return "ok"

    return WyomingServer(None, satellite_hub=hub, context_resolver=resolver, room_handler=room_handler,
                         require_authenticated_satellite=True)


async def _settle():
    for _ in range(5):
        await asyncio.sleep(0)


def test_the_capture_events_mean_what_they_say():
    assert LISTEN_EVENTS == {"detection": "listening", "voice-started": "listening", "voice-stopped": "thinking"}


def test_an_authenticated_satellite_lights_the_indicator_until_its_answer():
    async def run():
        seen = []
        server = _auth_server(seen)
        reader = asyncio.StreamReader()
        task = asyncio.create_task(server.handle_connection(reader, _Writer()))
        reader.feed_data(encode_event(WyomingEvent("satellite-auth", {"satellite_id": "kitchen"})))
        reader.feed_data(encode_event(WyomingEvent("detection", {"name": "jarvis"})))
        await _settle()
        assert listening.snapshot()["sources"] == {"satellite:kitchen": "listening"}
        reader.feed_data(encode_event(WyomingEvent("voice-stopped")))
        await _settle()
        assert listening.snapshot()["sources"] == {"satellite:kitchen": "thinking"}
        reader.feed_data(encode_event(WyomingEvent("transcript", {"text": "lights on"})))
        await _settle()
        assert seen == [{"satellite:kitchen": "thinking"}]
        assert listening.snapshot()["sources"] == {}, "answered: the satellite is done"
        reader.feed_data(encode_event(WyomingEvent("voice-started")))
        await _settle()
        assert listening.snapshot()["sources"] == {"satellite:kitchen": "listening"}
        reader.feed_eof()
        await task
        assert listening.snapshot()["sources"] == {}, "a closed connection leaves nothing lit"

    asyncio.run(run())


def test_a_satellite_that_drops_mid_capture_leaves_nothing_lit():
    async def run():
        server = _auth_server([])
        reader = asyncio.StreamReader()
        task = asyncio.create_task(server.handle_connection(reader, _Writer()))
        reader.feed_data(encode_event(WyomingEvent("satellite-auth", {"satellite_id": "kitchen"})))
        reader.feed_data(encode_event(WyomingEvent("detection")))
        await _settle()
        assert listening.snapshot()["sources"] == {"satellite:kitchen": "listening"}
        reader.feed_eof()                                  # gone before any transcript
        await task
        assert listening.snapshot()["sources"] == {}

    asyncio.run(run())


def test_an_unauthenticated_peer_cannot_light_the_indicator_when_auth_is_required():
    async def run():
        seen = []
        server = _auth_server(seen)
        reader = asyncio.StreamReader()
        writer = _Writer()
        task = asyncio.create_task(server.handle_connection(reader, writer))
        reader.feed_data(encode_event(WyomingEvent("detection", {"name": "jarvis"})))
        reader.feed_data(encode_event(WyomingEvent("voice-started")))
        await _settle()
        assert listening.snapshot()["sources"] == {}
        reader.feed_data(encode_event(WyomingEvent("transcript", {"text": "hi"})))
        await _settle()
        assert listening.snapshot()["sources"] == {} and seen == []
        reader.feed_eof()
        await task
        assert b"authentication_required" in bytes(writer.buf)

    asyncio.run(run())


def test_with_auth_off_the_one_anonymous_satellite_is_named():
    async def run():
        seen = []

        async def handler(text):
            seen.append(listening.snapshot()["sources"])
            return "ok"

        server = WyomingServer(handler)
        reader = asyncio.StreamReader()
        task = asyncio.create_task(server.handle_connection(reader, _Writer()))
        reader.feed_data(encode_event(WyomingEvent("detection")))
        await _settle()
        assert listening.snapshot()["sources"] == {"satellite": "listening"}
        reader.feed_data(encode_event(WyomingEvent("transcript", {"text": "hi"})))
        reader.feed_eof()
        await task
        assert seen == [{"satellite": "thinking"}] and listening.snapshot()["sources"] == {}

    asyncio.run(run())


def test_a_failing_answer_still_clears_the_satellite():
    async def run():
        server = WyomingServer(None)

        async def boom(event, *, context=None):
            raise RuntimeError("handler")

        server.dispatch = boom
        reader = asyncio.StreamReader()
        reader.feed_data(encode_event(WyomingEvent("transcript", {"text": "hi"})))
        reader.feed_eof()
        with pytest.raises(RuntimeError):
            await server.handle_connection(reader, _Writer())
        assert listening.snapshot()["sources"] == {}

    asyncio.run(run())


def test_other_events_still_reach_the_router():
    async def run():
        writer = _Writer()
        reader = asyncio.StreamReader()
        reader.feed_data(encode_event(WyomingEvent("detection")) + encode_event(WyomingEvent("ping", {"n": 1})))
        reader.feed_eof()
        await WyomingServer(None).handle_connection(reader, writer)
        assert b'"pong"' in bytes(writer.buf)

    asyncio.run(run())


# ── the read-only routes ─────────────────────────────────────────────────────


def test_get_listening_answers_the_snapshot():
    from agents.core.routers import voice as route

    listening.set_state("hub", "armed")
    response = asyncio.run(route.voice_listening())
    body = json.loads(response.body)
    assert body["state"] == "armed" and body["mic_open"] is True and body["sources"] == {"hub": "armed"}
    assert "no-store" in response.headers.get("cache-control", "")


def test_the_stream_sends_a_frame_per_change_and_keeps_alive_between():
    from agents.core.routers import voice as route

    snaps = iter([{"state": "off", "seq": 0}, {"state": "off", "seq": 0}, {"state": "off", "seq": 0},
                  {"state": "armed", "seq": 1}, {"state": "armed", "seq": 1}])

    async def nosleep(_):
        return None

    async def collect():
        return [f async for f in route.listening_events(lambda: next(snaps), sleep=nosleep, keepalive_every=2,
                                                        max_iterations=5)]

    frames = asyncio.run(collect())
    assert frames == [
        'data: {"type": "listening", "state": "off", "seq": 0}\n\n',
        ": keepalive\n\n",
        'data: {"type": "listening", "state": "armed", "seq": 1}\n\n',
    ]


def test_a_change_restarts_the_keepalive_count():
    from agents.core.routers import voice as route

    snaps = iter([{"seq": 0}, {"seq": 0}, {"seq": 1}, {"seq": 1}])

    async def nosleep(_):
        return None

    async def collect():
        return [f async for f in route.listening_events(lambda: next(snaps), sleep=nosleep, keepalive_every=2,
                                                        max_iterations=4)]

    assert asyncio.run(collect()) == ['data: {"type": "listening", "seq": 0}\n\n',
                                      'data: {"type": "listening", "seq": 1}\n\n']


def test_the_stream_reads_the_live_registry_by_default():
    from agents.core.routers import voice as route

    listening.set_state("hub", "listening")

    async def nosleep(_):
        return None

    async def first():
        gen = route.listening_events(sleep=nosleep, max_iterations=1)
        return [f async for f in gen]

    frame = asyncio.run(first())[0]
    assert '"state": "listening"' in frame and '"mic_open": true' in frame


def test_the_routes_are_user_guarded_and_read_only():
    snapshot = json.loads((ROOT / "tests" / "_snapshots" / "route_auth.json").read_text(encoding="utf-8"))
    assert snapshot["GET /api/voice/listening"] == "user"
    assert snapshot["GET /api/voice/listening/stream"] == "user"
    assert not any(k.split(" ", 1)[1].startswith("/api/voice/listening") and not k.startswith("GET ")
                   for k in snapshot), "nothing can set the listening state over HTTP"
    from agents import web
    from tests._route_introspect import iter_effective_routes

    found = {r.path: r for r in iter_effective_routes(web.app)
             if getattr(r, "path", "").startswith("/api/voice/listening") and hasattr(r, "dependant")}
    assert set(found) == {"/api/voice/listening", "/api/voice/listening/stream"}
    for r in found.values():
        assert r.methods == {"GET"}
        assert "user_guard" in {getattr(d.call, "__name__", "") for d in r.dependant.dependencies}


# ── the desktop shell ────────────────────────────────────────────────────────


def test_the_shell_exposes_one_read_only_listening_command_to_its_own_windows():
    tauri = ROOT / "desktop" / "src-tauri"
    main = (tauri / "src" / "main.rs").read_text(encoding="utf-8")
    assert "mod indicator;" in main
    assert "fn desktop_listening(" in main
    body = main.split("fn desktop_listening(", 1)[1].split("\nfn ", 1)[0]
    assert "verify(&window)?;" in body, "only the local HUD windows may report"
    assert "indicator::parse(&state)?" in body and "board.report(window.label()" in body
    assert "set_tooltip(Some(shown.tooltip()))" in body and "set_title(shown.title())" in body
    assert ".manage(indicator::Board::default())" in main
    assert "desktop_listening\n" in main.split("generate_handler![", 1)[1].split("]", 1)[0] + "\n"
    assert "TrayIconBuilder::with_id(TRAY_ID)" in main and 'const TRAY_ID: &str = "nerva";' in main
    build = (tauri / "build.rs").read_text(encoding="utf-8")
    assert '"desktop_listening"' in build
    caps = json.loads((tauri / "capabilities" / "desktop.json").read_text(encoding="utf-8"))
    assert "allow-desktop-listening" in caps["permissions"] and caps["windows"] == ["main", "floating"]
    perm = (tauri / "permissions" / "autogenerated" / "desktop_listening.toml").read_text(encoding="utf-8")
    assert 'commands.allow = ["desktop_listening"]' in perm


@pytest.mark.skipif(sys.platform == "win32", reason="rustc test harness on POSIX CI hosts")
def test_the_indicator_under_rustc(tmp_path):
    import shutil as _sh

    rustc = _sh.which("rustc")
    if rustc is None:
        pytest.skip("rustc is not installed")
    src = ROOT / "desktop" / "src-tauri" / "src" / "indicator.rs"
    out = tmp_path / "indicator_tests"
    built = subprocess.run([rustc, "--edition", "2021", "--test", str(src), "-o", str(out)],
                           capture_output=True, text=True, timeout=300)
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(out)], capture_output=True, text=True, timeout=60)
    assert ran.returncode == 0 and "test result: ok" in ran.stdout, ran.stdout + ran.stderr
