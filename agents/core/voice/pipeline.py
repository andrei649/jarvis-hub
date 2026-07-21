"""
voice.py — Voice pipeline coordinator.
Manages wake word → STT → response → TTS cycle.
"""

import asyncio
import logging
from typing import Callable, Optional

from agents.core.paths import data_path

from .stt import STTEngine
from .tts import TTSEngine
from .wake_word import WakeWordDetector

logger = logging.getLogger("jarvis.voice")


class VoicePipeline:
    def __init__(self, on_transcription: Callable = None):
        self.detector = WakeWordDetector(callback=self._on_wake_word)
        from ..settings_db import get_value
        self.stt = STTEngine(model_size=get_value("voice", "stt_model_size", "medium"), device="auto")
        self.tts = TTSEngine(default_voice=get_value("voice", "tts_voice", "en-GB-RyanNeural"))
        self.on_transcription = on_transcription
        self._running = False
        self._last_audio: Optional[str] = None

    async def start(self):
        self._running = True
        logger.info("Voice pipeline started")
        await self.detector.start()

    def stop(self):
        self._running = False
        self.detector.stop()
        logger.info("Voice pipeline stopped")

    def _on_wake_word(self, word: str):
        logger.info(f"Wake: {word}")
        task = asyncio.create_task(self._capture_and_process(word))
        # B6: surface exceptions from the fire-and-forget capture task.
        task.add_done_callback(
            lambda t: logger.error("wake-word processing failed: %s", t.exception(), exc_info=t.exception())
            if not t.cancelled() and t.exception() else None)

    async def _capture_and_process(self, wake_word: str):
        audio_path = await self._record_audio()
        if not audio_path:
            return

        text = await self.stt.transcribe_async(audio_path)
        if not text or text == "[silence]":
            return

        logger.info(f"STT: {text}")
        if self.on_transcription:
            response = await self.on_transcription(text)
            if response:
                audio_out = await self.tts.speak(response)
                if audio_out:
                    await self._play_audio(audio_out)

    async def _record_audio(self) -> Optional[str]:
        """Record from mic until silence (off the event loop). Returns temp path."""
        return await asyncio.to_thread(self._record_audio_blocking)

    def _record_audio_blocking(self) -> Optional[str]:
        """Blocking PyAudio capture + wave write — must run in a worker thread."""
        try:
            import wave

            import numpy as np
            import pyaudio

            CHUNK = 1024
            FORMAT = pyaudio.paInt16
            CHANNELS = 1
            RATE = 16000
            SILENCE_SECS = 1.5
            MAX_SECS = 15

            p = pyaudio.PyAudio()
            stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                           input=True, frames_per_buffer=CHUNK)

            frames = []
            silent_chunks = 0
            silence_threshold = int(RATE / CHUNK * SILENCE_SECS)
            max_chunks = int(RATE / CHUNK * MAX_SECS)
            started = False

            for _ in range(max_chunks):
                data = stream.read(CHUNK, exception_on_overflow=False)
                frames.append(data)
                audio_np = np.frombuffer(data, dtype=np.int16)
                volume = np.abs(audio_np).mean()

                if volume > 200:
                    started = True
                    silent_chunks = 0
                elif started:
                    silent_chunks += 1

                if started and silent_chunks >= silence_threshold:
                    break

            stream.stop_stream()
            stream.close()
            p.terminate()

            if not frames or not started:
                return None

            out_path = str(TEMP_DIR / f"input_{abs(hash(str(frames[-1])))}.wav")
            with wave.open(out_path, "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(p.get_sample_size(FORMAT))
                wf.setframerate(RATE)
                wf.writeframes(b"".join(frames))
            return out_path

        except Exception as e:
            logger.error(f"Record error: {e}")
            return None

    async def _play_audio(self, path: str):
        try:
            import pygame
            pygame.mixer.init()
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Playback error: {e}")


TEMP_DIR = data_path("audio")
