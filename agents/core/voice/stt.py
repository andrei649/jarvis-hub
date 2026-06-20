"""
stt.py — Speech-to-text via faster-whisper (GPU-accelerated on CUDA).
Falls back to a simple placeholder if not installed.

Tuned for the live browser-HUD loop (short, clear utterances), where latency
matters more than squeezing out the last fraction of accuracy:
  * beam_size defaults to 1 (greedy) — beam search (the old default of 5) is the
    single costliest decode knob and buys little on short commands.
  * compute_type defaults to int8_float16 on CUDA (≈ same speed as float16 but
    frees ~1.5GB VRAM the LLM slots want) and int8 on CPU.
Both are overridable per instance or via env (JARVIS_STT_BEAM_SIZE,
JARVIS_STT_COMPUTE_TYPE) so a transcription-quality job can opt back into
beam search without a code change.
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

# Greedy decode by default for the live loop; override with JARVIS_STT_BEAM_SIZE.
DEFAULT_BEAM_SIZE = 1


def _resolve_beam_size(override: Optional[int]) -> int:
    if override is not None:
        return override
    try:
        return int(os.environ.get("JARVIS_STT_BEAM_SIZE", DEFAULT_BEAM_SIZE))
    except (TypeError, ValueError):
        return DEFAULT_BEAM_SIZE


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

    def transcribe(self, audio_path: str, language: str = "ro") -> str:
        if not self._model:
            return "[STT unavailable]"

        try:
            segments, info = self._model.transcribe(
                audio_path,
                language=language,
                beam_size=self.beam_size,
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
