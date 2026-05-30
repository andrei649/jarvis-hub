import logging
from typing import Optional

logger = logging.getLogger("voice.tts")

# Kokoro voice mappings: (lang_code, voice) per language
VOICE_MAP: dict[str, tuple[str, str]] = {
    "ro": ("a", "af_heart"),       # Romanian → American English (closest available)
    "en": ("a", "af_bella"),        # English - American
    "en-gb": ("b", "bm_george"),    # English - British
    "jp": ("j", "jf_kumo"),         # Japanese
    "kr": ("k", "kf_doyeon"),       # Korean
    "zh": ("z", "zf_xiaobei"),      # Mandarin Chinese
}

DEFAULT_LANG = "ro"
DEFAULT_VOICE = "af_heart"

# Per-agent signature voices (local Kokoro presets — no cloud cloning).
# Maps agent_id -> (lang, voice). Lets JARVIS carry a distinct timbre.
AGENT_VOICE_MAP: dict[str, tuple[str, str]] = {
    "jarvis": ("en-gb", "bm_george"),   # British male — signature JARVIS timbre
}


class TextToSpeech:
    def __init__(self, lang: str = "ro", voice: Optional[str] = None, speed: float = 1.0):
        self.lang = lang
        self.voice = voice
        self.speed = speed
        self._pipeline = None

    @classmethod
    def for_agent(cls, agent_id: str, speed: float = 1.0) -> "TextToSpeech":
        """Build a TTS instance using an agent's signature voice if defined."""
        if agent_id in AGENT_VOICE_MAP:
            lang, voice = AGENT_VOICE_MAP[agent_id]
            return cls(lang=lang, voice=voice, speed=speed)
        return cls(speed=speed)


    def load(self):
        lang_code, default_voice = VOICE_MAP.get(self.lang, ("a", "af_heart"))
        if self.voice is None:
            self.voice = default_voice
        try:
            from kokoro import KPipeline
            self._pipeline = KPipeline(lang_code=lang_code)
            logger.info(f"Kokoro TTS loaded (lang={lang_code}, voice={self.voice})")
        except Exception as e:
            logger.warning(f"Kokoro not available: {e}")

    def synthesize(self, text: str) -> Optional[bytes]:
        if self._pipeline is None:
            return None
        try:
            generator = self._pipeline(text, voice=self.voice, speed=self.speed)
            audio_parts = []
            for _, _, audio in generator:
                if audio is not None:
                    audio_parts.append(audio)
            if audio_parts:
                import numpy as np
                import soundfile as sf
                import io
                combined = np.concatenate(audio_parts)
                buf = io.BytesIO()
                sf.write(buf, combined, 24000, format="WAV")
                return buf.getvalue()
        except Exception as e:
            logger.error(f"TTS synthesis error: {e}")
        return None

    def is_loaded(self) -> bool:
        return self._pipeline is not None

    def set_voice(self, voice: str):
        self.voice = voice

    def set_lang(self, lang: str):
        self.lang = lang
        self.load()
