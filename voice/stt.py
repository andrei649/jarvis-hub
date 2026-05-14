import logging
from typing import Optional

import numpy as np

logger = logging.getLogger("voice.stt")


class SpeechToText:
    def __init__(
        self,
        model_size: str = "large-v3",
        device: str = "cpu",
        compute_type: str = "float16",
        language: Optional[str] = "ro",
    ):
        self.model_size = model_size
        self.device = device
        self.compute_type = "int8" if device == "cpu" else compute_type
        self.language = language
        self._model = None

    def load(self):
        try:
            from faster_whisper import WhisperModel

            try:
                self._model = WhisperModel(
                    self.model_size, device=self.device, compute_type=self.compute_type
                )
            except Exception:
                logger.warning(f"Failed with device='{self.device}', falling back to cpu")
                self._model = WhisperModel(
                    self.model_size, device="cpu", compute_type="int8"
                )
            logger.info(
                f"Whisper {self.model_size} loaded (device={self.device}, lang={self.language})"
            )
        except Exception as e:
            logger.error(f"Failed to load Whisper: {e}")

    def transcribe(self, audio: np.ndarray, language: Optional[str] = None) -> Optional[str]:
        if self._model is None:
            return None
        try:
            lang = language or self.language
            segments, info = self._model.transcribe(audio, beam_size=1, language=lang)
            logger.debug(
                f"Transcribed {len(audio)} samples "
                f"(lang={info.language}, prob={info.language_probability:.2f})"
            )
            return " ".join(seg.text for seg in segments) or None
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return None

    def is_loaded(self) -> bool:
        return self._model is not None
