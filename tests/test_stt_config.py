"""Tests for STT decode-config resolution (perf quick win #3).

faster-whisper isn't installed in the offline suite, so the model never loads;
these cover the pure config resolution + that transcribe() forwards the
configured beam_size. The defaults bias the live HUD loop toward latency
(greedy decode, int8 compute).
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.voice.stt import (
    STTEngine,
    _resolve_beam_size,
    _resolve_compute_type,
    DEFAULT_BEAM_SIZE,
)


def test_beam_size_defaults_to_greedy():
    assert DEFAULT_BEAM_SIZE == 1
    assert _resolve_beam_size(None) == 1


def test_beam_size_explicit_override_wins():
    assert _resolve_beam_size(5) == 5


def test_beam_size_env_override(monkeypatch):
    monkeypatch.setenv("JARVIS_STT_BEAM_SIZE", "4")
    assert _resolve_beam_size(None) == 4


def test_beam_size_bad_env_falls_back(monkeypatch):
    monkeypatch.setenv("JARVIS_STT_BEAM_SIZE", "not-an-int")
    assert _resolve_beam_size(None) == DEFAULT_BEAM_SIZE


def test_compute_type_cuda_vs_cpu():
    assert _resolve_compute_type("cuda", None) == "int8_float16"
    assert _resolve_compute_type("cpu", None) == "int8"


def test_compute_type_override_wins():
    assert _resolve_compute_type("cuda", "float16") == "float16"


def test_compute_type_env_override(monkeypatch):
    monkeypatch.setenv("JARVIS_STT_COMPUTE_TYPE", "float32")
    assert _resolve_compute_type("cuda", None) == "float32"


class _FakeSeg:
    def __init__(self, text):
        self.text = text


class _FakeModel:
    def __init__(self):
        self.kwargs = None

    def transcribe(self, audio_path, language, beam_size, vad_filter):
        self.kwargs = dict(language=language, beam_size=beam_size, vad_filter=vad_filter)
        return ([_FakeSeg("hello"), _FakeSeg(" world")], None)


def test_transcribe_forwards_configured_beam_size():
    eng = STTEngine(beam_size=3)
    assert eng.beam_size == 3
    fake = _FakeModel()
    eng._model = fake
    out = eng.transcribe("clip.wav", language="en")
    assert out == "hello  world"
    assert fake.kwargs["beam_size"] == 3
    assert fake.kwargs["language"] == "en"
    assert fake.kwargs["vad_filter"] is True


def test_transcribe_unavailable_without_model():
    eng = STTEngine()
    eng._model = None
    assert eng.transcribe("clip.wav") == "[STT unavailable]"
