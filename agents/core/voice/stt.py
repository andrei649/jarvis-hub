"""
stt.py — Speech-to-text via faster-whisper (GPU-accelerated on CUDA).
Falls back to a simple placeholder if not installed.

Tuned for the live browser-HUD loop (short, clear utterances), where latency
matters more than squeezing out the last fraction of accuracy:
  * beam_size defaults to 1 (greedy) — beam search (the old default of 5) is the
    single costliest decode knob and buys little on short commands.
  * compute_type defaults to int8_float16 on CUDA (≈ same speed as float16 but
    frees VRAM for the LLM slots — order of ~0.5-0.8GB on the default `medium`
    model; the ~1.5GB figure in the faster-whisper README is for large-v3) and
    int8 on CPU.
Both are overridable per instance or via env (JARVIS_STT_BEAM_SIZE,
JARVIS_STT_COMPUTE_TYPE) so a transcription-quality job can opt back into
beam search without a code change.

H613 — the owner's approved STT command provider (``voice.stt_command``, see
``local_providers``) transcribes instead when ``voice.stt_engine`` is ``command``, or is
``auto`` and faster-whisper is absent or failed to load. ``whisper`` never uses it.
"""

import asyncio
import io
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from agents.core.env_config import env_int
from agents.core.voice import local_providers
from agents.core.voice.hallucination import is_hallucination

logger = logging.getLogger("jarvis.voice.stt")

try:
    from faster_whisper import WhisperModel
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False

# Greedy decode by default for the live loop; override with JARVIS_STT_BEAM_SIZE.
DEFAULT_BEAM_SIZE = 1
#: Where an STT command's private run directories live (the TTS temp dir, H613).
TEMP_DIR = Path(tempfile.gettempdir()) / "cabinet_tts"


def _resolve_beam_size(override: Optional[int]) -> int:
    if override is not None:
        return override
    return env_int("JARVIS_STT_BEAM_SIZE", DEFAULT_BEAM_SIZE, minimum=1)


def _resolve_compute_type(device: str, override: Optional[str]) -> str:
    """Pick a CTranslate2 compute type. int8_float16 is a CUDA-only combo, so
    fall back to plain int8 on CPU. Env/explicit override always wins."""
    env = override or os.environ.get("JARVIS_STT_COMPUTE_TYPE")
    if env:
        return env
    return "int8_float16" if device == "cuda" else "int8"


class STTEngine:
    def __init__(
        self,
        model_size: str = "medium",
        device: str = "auto",
        beam_size: Optional[int] = None,
        compute_type: Optional[str] = None,
    ):
        self.model_size = model_size
        self.device = device
        self.beam_size = _resolve_beam_size(beam_size)
        self._compute_type_override = compute_type
        self._model = None
        if HAS_WHISPER:
            self._init_model()

    def _init_model(self):
        try:
            if self.device == "auto":
                import torch
                self.device = "cuda" if torch.cuda.is_available() else "cpu"
            compute = _resolve_compute_type(self.device, self._compute_type_override)
            self.compute_type = compute
            self._model = WhisperModel(self.model_size, device=self.device, compute_type=compute)
            logger.info(
                f"Whisper loaded: {self.model_size} on {self.device} "
                f"(compute={compute}, beam_size={self.beam_size})"
            )
        except Exception as e:
            logger.warning(f"Whisper init failed: {e}")
            self._model = None

    def transcribe(self, audio, language: str = "ro") -> str:
        """Transcribe *audio* — a path, raw bytes, or any binary file object.

        Bytes are accepted so a caller holding a recording in memory (an inbound
        voice note off a chat channel) never has to write someone's speech to
        disk to have it read. faster-whisper decodes a file object the same way
        it decodes a path.

        A transcript that is only Whisper talking to itself comes back as
        ``[silence]`` — see :mod:`agents.core.voice.hallucination`. That is the
        sentinel this method already returned for genuinely empty audio, and
        every existing caller treats a leading ``[`` as "nothing was said"
        (`routers/voice.py` skips dictation cleanup on it, `frontend/src/voice.ts`
        drops it), so the filter needs no new contract to be honoured.
        """
        if self._use_command():
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(self._transcribe_command(audio, language))
            return "[STT error: command STT needs an async caller]"
        if not self._model:
            return "[STT unavailable]"

        try:
            segments, info = self._model.transcribe(
                self._as_source(audio),
                language=language,
                beam_size=self.beam_size,
                vad_filter=True,
            )
            text = " ".join(seg.text for seg in segments).strip()
            if not text:
                return "[silence]"
            # The duration comes from the decoded audio, not from whoever sent
            # it: it is what actually reached the decoder, so a short-recording
            # rule cannot be steered by a number in an envelope.
            seconds = getattr(info, "duration", None)
            if is_hallucination(text, audio_seconds=seconds):
                logger.info("STT: discarded a silence hallucination (%.2fs)",
                            float(seconds) if isinstance(seconds, (int, float)) else -1.0)
                return "[silence]"
            return text
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return f"[STT error: {e}]"

    @staticmethod
    def _as_source(audio):
        """Bytes become an in-memory stream; a path or file object passes through."""
        if isinstance(audio, (bytes, bytearray, memoryview)):
            return io.BytesIO(bytes(audio))
        return audio

    def _use_command(self) -> bool:
        """Whether the approved STT command transcribes (H613): ``voice.stt_engine`` is
        ``command``, or ``auto`` with no Whisper model — and the command is ready now."""
        mode = local_providers.stt_mode()
        if mode == "whisper" or (mode == "auto" and self._model is not None):
            return False
        return local_providers.command_ready("stt").ok

    async def _transcribe_command(self, audio, language) -> str:
        from agents.core.settings_db import get_value

        default = get_value("voice", "stt_language", "en")
        return await local_providers.transcribe_command(audio, language, temp_dir=TEMP_DIR,
                                                        default_lang=default if isinstance(default, str) else "en")

    async def transcribe_async(self, audio, language: str = "ro") -> str:
        if self._use_command():
            return await self._transcribe_command(audio, language)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.transcribe, audio, language)
