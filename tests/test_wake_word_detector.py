"""The wake-word detector must start against the real openwakeword API (`Model`,
16-bit sample frames) and fire on a pretrained model such as hey_jarvis."""

import asyncio
import sys
import types

import numpy as np
import pytest

from agents.core.voice import wake_word


class _FakeModel:
    frames = []

    def __init__(self, *args, **kwargs):
        pass

    def predict(self, frame):
        _FakeModel.frames.append(frame)
        return {"alexa_v0.1": 0.01, "hey_jarvis_v0.1": 0.93}


class _Stream:
    def read(self, n):
        return b"\x01\x00" * n

    def stop_stream(self):
        pass

    def close(self):
        pass


class _Audio:
    def open(self, **kwargs):
        return _Stream()

    def terminate(self):
        pass


@pytest.fixture
def fakes(monkeypatch):
    # Only the real package's public name: openwakeword exports Model, never OWWModel.
    monkeypatch.setattr(wake_word, "openwakeword", types.SimpleNamespace(Model=_FakeModel), raising=False)
    monkeypatch.setattr(wake_word, "pyaudio", types.SimpleNamespace(PyAudio=_Audio, paInt16=8), raising=False)
    monkeypatch.setattr(wake_word, "HAS_OWW", True)
    monkeypatch.setattr(wake_word, "HAS_PYAUDIO", True)
    _FakeModel.frames.clear()


def test_detector_starts_and_fires_on_a_pretrained_model(fakes):
    heard = []
    detector = None

    def on_wake(word):
        heard.append(word)
        detector.stop()

    detector = wake_word.WakeWordDetector(callback=on_wake)
    asyncio.run(asyncio.wait_for(detector.start(), timeout=5))
    assert heard == ["jarvis"]
    frame = _FakeModel.frames[0]
    assert isinstance(frame, np.ndarray) and frame.dtype == np.int16 and frame.size == 1280


def test_low_scores_and_unrelated_models_do_not_fire():
    detector = wake_word.WakeWordDetector()
    assert detector._matched({"hey_jarvis_v0.1": 0.2, "alexa": 0.99}) is None
    assert detector._matched({"hey_jarvis": 0.8}) == "jarvis"
    assert detector._matched({}) is None


def test_the_real_package_exports_model_not_owwmodel():
    try:
        import openwakeword
    except ImportError:
        pytest.skip("openwakeword not installed")
    assert hasattr(openwakeword, "Model")
