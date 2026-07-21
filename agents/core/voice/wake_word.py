"""
wake_word.py — Wake word detection via openWakeWord.
Continuously listens on a microphone stream and fires callback on detection.
Supports: "jarvis", "hub"
"""

import asyncio
import logging
from typing import Callable

logger = logging.getLogger("jarvis.voice.wake_word")

try:
    import openwakeword
    HAS_OWW = True
except ImportError:
    HAS_OWW = False

try:
    import pyaudio
    HAS_PYAUDIO = True
except ImportError:
    HAS_PYAUDIO = False


class WakeWordDetector:
    WAKE_WORDS = ["jarvis", "hub"]

    def __init__(self, callback: Callable[[str], None] = None):
        self.callback = callback
        self._running = False
        self._owl = None
        self._stream = None
        self._audio = None

    async def start(self):
        if not HAS_OWW:
            logger.warning("openwakeword not installed. Install: pip install openwakeword")
            return
        if not HAS_PYAUDIO:
            logger.warning("pyaudio not installed. Install: pip install pyaudio")
            return

        self._owl = openwakeword.OWWModel()
        self._audio = pyaudio.PyAudio()
        self._stream = self._audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,
            input=True,
            frames_per_buffer=1280,
        )
        self._running = True
        logger.info("Wake word detection started")
        await self._listen_loop()

    async def _listen_loop(self):
        loop = asyncio.get_event_loop()
        while self._running:
            try:
                pcm = await loop.run_in_executor(None, self._stream.read, 1280)
                prediction = await loop.run_in_executor(None, self._owl.predict, pcm)
                for ww in self.WAKE_WORDS:
                    if ww in prediction and prediction[ww] > 0.5:
                        logger.info(f"Wake word detected: {ww}")
                        if self.callback:
                            # Call on THIS (loop) thread, not a pool worker: the
                            # callback (VoicePipeline._on_wake_word) only schedules
                            # a task via asyncio.create_task, which needs a running
                            # loop — from an executor thread it raises RuntimeError.
                            self.callback(ww)
            except Exception as e:
                logger.error(f"Wake word error: {e}")
                await asyncio.sleep(0.1)

    def stop(self):
        self._running = False
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
        if self._audio:
            self._audio.terminate()
        logger.info("Wake word detection stopped")
