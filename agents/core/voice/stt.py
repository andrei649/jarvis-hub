"""
stt.py — Speech-to-text via faster-whisper (GPU-accelerated on CUDA).
Falls back to a simple placeholder if not installed.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger("jarvis.voice.stt")

try:
    from faster_whisper import WhisperModel
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False


class STTEngine:
    def __init__(self, model_size: str = "medium", device: str = "auto"):
        self.model_size = model_size
        self.device = device
        self._model = None
        if HAS_WHISPER:
            self._init_model()

    def _init_model(self):
        try:
            compute = "float16"
            if self.device == "auto":
                import torch
                self.device = "cuda" if torch.cuda.is_available() else "cpu"
            self._model = WhisperModel(self.model_size, device=self.device, compute_type=compute)
            logger.info(f"Whisper loaded: {self.model_size} on {self.device}")
        except Exception as e:
            logger.warning(f"Whisper init failed: {e}")
            self._model = None

    def transcribe(self, audio_path: str, language: str = "ro") -> str:
        if not self._model:
            return "[STT unavailable]"

        try:
            segments, info = self._model.transcribe(
                audio_path,
                language=language,
                beam_size=5,
                vad_filter=True,
            )
            text = " ".join(seg.text for seg in segments)
            return text.strip() or "[silence]"
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return f"[STT error: {e}]"

    async def transcribe_async(self, audio_path: str, language: str = "ro") -> str:
        loop = __import__("asyncio").get_event_loop()
        return await loop.run_in_executor(None, self.transcribe, audio_path, language)
