import asyncio
import logging
import struct
from enum import Enum
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger("voice.manager")

SAMPLE_RATE = 16000
CHUNK_SIZE = 1600       # 100ms per chunk
SILENCE_FRAMES = 20      # 2s of silence = stop recording
MIN_COMMAND_SECONDS = 0.5
MAX_COMMAND_SECONDS = 15


class VoiceState(Enum):
    IDLE = "idle"
    WAKE_PENDING = "wake_pending"
    RECORDING = "recording"


class VoiceManager:
    def __init__(self):
        from .wake_word import WakeWordDetector
        from .stt import SpeechToText
        from .tts import TextToSpeech

        self.wake = WakeWordDetector()
        self.stt = SpeechToText()
        self.tts = TextToSpeech()
        self._state = VoiceState.IDLE
        self._on_command: Optional[Callable] = None
        self._capture_task: Optional[asyncio.Task] = None
        self._input_stream = None
        self._audio_queue: asyncio.Queue[np.ndarray] = asyncio.Queue()

    def load_all(self):
        self.wake.load()
        self.stt.load()
        self.tts.load()

    async def start_listening(self, on_command_callback: Optional[Callable] = None):
        self._on_command = on_command_callback
        self._capture_task = asyncio.create_task(self._capture_loop())
        logger.info("Voice manager started — listening for wake word")

    async def stop_listening(self):
        if self._capture_task:
            self._capture_task.cancel()
            self._capture_task = None
        if self._input_stream:
            self._input_stream.close()
            self._input_stream = None
        self._state = VoiceState.IDLE
        logger.info("Voice manager stopped")

    async def process_audio(self, audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> Optional[str]:
        if self._state == VoiceState.IDLE:
            ww = self.wake.listen(audio)
            if ww:
                logger.info(f"Wake word '{ww}' detected — starting command capture")
                self._state = VoiceState.RECORDING
                self._command_buffer = [audio]
                self._silence_counter = 0
        elif self._state == VoiceState.RECORDING:
            if not hasattr(self, "_command_buffer"):
                self._command_buffer = []
            self._command_buffer.append(audio)
            rms = np.sqrt(np.mean(audio ** 2))
            if rms < 0.02:
                self._silence_counter += 1
            else:
                self._silence_counter = 0
            total_seconds = sum(len(c) for c in self._command_buffer) / sample_rate
            if total_seconds > MAX_COMMAND_SECONDS:
                logger.info("Max command length reached, processing...")
                return await self._process_command(sample_rate)
            if total_seconds > MIN_COMMAND_SECONDS and self._silence_counter >= SILENCE_FRAMES:
                logger.info("Silence detected after command, processing...")
                return await self._process_command(sample_rate)
        return None

    async def _process_command(self, sample_rate: int) -> Optional[str]:
        self._state = VoiceState.IDLE
        if not hasattr(self, "_command_buffer") or not self._command_buffer:
            return None
        audio = np.concatenate(self._command_buffer)
        self._command_buffer = []
        logger.info(f"Transcribing {len(audio)} samples...")
        text = self.stt.transcribe(audio)
        if text and self._on_command:
            logger.info(f"Command: {text}")
            await self._on_command(text.strip())
        return text

    async def _capture_loop(self):
        try:
            import sounddevice as sd
        except ImportError:
            logger.warning("sounddevice not installed — mic capture disabled")
            return

        def audio_callback(indata, frames, time_info, status):
            if status:
                logger.debug(f"Mic status: {status}")
            chunk = indata.copy()
            self._audio_queue.put_nowait(chunk.flatten())

        try:
            self._input_stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                blocksize=CHUNK_SIZE,
                callback=audio_callback,
                dtype="float32",
            )
            self._input_stream.start()
            logger.info(f"Mic capture started ({SAMPLE_RATE}Hz, {CHUNK_SIZE} frames)")
        except Exception as e:
            logger.warning(f"Mic not available: {e}")
            return

        while True:
            try:
                chunk = await self._audio_queue.get()
                await self.process_audio(chunk, SAMPLE_RATE)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Audio capture error: {e}")

    async def speak(self, text: str) -> Optional[bytes]:
        return self.tts.synthesize(text)
