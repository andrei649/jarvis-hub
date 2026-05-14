import logging
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger("voice.wake")


class WakeWordDetector:
    def __init__(
        self,
        model_dir: str = "voice/models",
        wake_words: Optional[list[str]] = None,
        threshold: float = 0.5,
    ):
        self.threshold = threshold
        self._wake_words = wake_words or ["hey_jarvis", "jarvis"]
        self._model = None
        self._model_dir = Path(model_dir)
        self._model_dir.mkdir(parents=True, exist_ok=True)

    def load(self):
        try:
            import openwakeword

            custom_paths = list(self._model_dir.glob("*.onnx"))
            if custom_paths:
                self._model = openwakeword.Model(wakeword_model_paths=custom_paths)
                logger.info(f"Wake word model loaded (custom: {[p.name for p in custom_paths]})")
            else:
                self._model = openwakeword.Model()
                logger.info(f"Wake word model loaded (built-in), listening for: {self._wake_words}")
        except Exception as e:
            logger.warning(f"Wake word model not available: {e}")
            self._model = None

    def listen(self, audio_chunk: np.ndarray, sample_rate: int = 16000) -> Optional[str]:
        if self._model is None:
            return None
        try:
            prediction = self._model.predict(audio_chunk)
        except Exception:
            return None
        for ww in self._wake_words:
            score = prediction.get(ww, 0)
            if score > self.threshold:
                logger.info(f"Wake word detected: '{ww}' (score: {score:.3f})")
                return ww
        return None

    def has_model(self) -> bool:
        return self._model is not None
